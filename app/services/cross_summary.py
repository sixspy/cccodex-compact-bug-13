"""跨表汇总体积：独立快照表单轨补洞。

规则：
- 汇总必须覆盖全部应纳入的湖表；漏表时灯色不得为绿灯，快照须标出未纳入表名。
- 快照头 + 逐表明细 + 灯色在同一个事务里一次写完，失败整体回滚。
- 进程内锁 + BEGIN IMMEDIATE，防止两侧仓管并发补洞双写、互相覆盖。
- 汇总字节必须与逐表明细之和对齐，偏了拒绝落库（挡落库）。
"""
from __future__ import annotations

import json
import threading

from app.db import get_db
from app.services.errors import ServiceError

# 应纳入跨表汇总的全部湖表（与种子/登记面同源）。
CANONICAL_TABLES = ["dw_orders", "dw_payments", "dw_users"]
GREEN = "绿灯"
RED = "漏表汇总"

# 仓管两侧可能同时点“生成汇总”，用进程锁串行化，配合 BEGIN IMMEDIATE 防双写覆盖。
_snapshot_lock = threading.Lock()


def _requested_tables(tables: list[str] | None, conn) -> list[str]:
    if tables:
        # 去重保序，拒绝空表名。
        seen: set[str] = set()
        out: list[str] = []
        for tb in tables:
            tb = (tb or "").strip()
            if tb and tb not in seen:
                seen.add(tb)
                out.append(tb)
        if not out:
            raise ServiceError("纳入表清单不能为空")
        return out
    # 缺省取湖区现存全部表，并回退到规范清单，保证不漏表。
    rows = conn.execute(
        "SELECT DISTINCT table_name FROM lake_files ORDER BY table_name"
    ).fetchall()
    live = [r["table_name"] for r in rows]
    return live or list(CANONICAL_TABLES)


def _read_table_bytes(conn, tables: list[str]) -> list[dict]:
    detail = []
    for tb in tables:
        row = conn.execute(
            "SELECT COALESCE(SUM(size_bytes),0) AS s FROM lake_files WHERE table_name=?",
            (tb,),
        ).fetchone()
        detail.append({"table": tb, "bytes": int(row["s"])})
    return detail


def _read_live_tables(conn) -> set[str]:
    return {
        r["table_name"]
        for r in conn.execute(
            "SELECT DISTINCT table_name FROM lake_files"
        ).fetchall()
    }


def summarize(tables: list[str] | None = None, db_path: str | None = None) -> dict:
    """生成跨表汇总并一次写完独立快照；返回快照内容。

    漏表：湖区存在但本次未纳入的表。漏表或字节不对齐时灯色为“漏表汇总”，
    且任何情况下灯色都不允许脱离纳入清单单独写绿。
    """
    explicit_empty = tables is not None and not tables
    with _snapshot_lock:
        with get_db(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if explicit_empty:
                raise ServiceError("纳入表清单不能为空")
            requested = _requested_tables(tables, conn)
            detail = _read_table_bytes(conn, requested)
            total = sum(d["bytes"] for d in detail)

            live_tables = _read_live_tables(conn)
            missing = sorted(live_tables - set(requested))

            # 汇总字节必须与湖区全量直算值对齐；偏了挡落库（不写任何快照）。
            truth_total = int(
                conn.execute(
                    "SELECT COALESCE(SUM(size_bytes),0) AS s FROM lake_files"
                ).fetchone()["s"]
            )
            if not missing and total != truth_total:
                raise ServiceError("汇总字节与各表字节不对齐，已挡落库")

            aligned = not missing
            chip = GREEN if aligned else RED

            cur = conn.execute(
                "INSERT INTO cross_summary_snapshot"
                "(total_bytes, included_count, requested_count, missing_tables, chip, aligned) "
                "VALUES (?,?,?,?,?,?)",
                (total, len(requested), len(requested), json.dumps(missing, ensure_ascii=False),
                 chip, 1 if aligned else 0),
            )
            snapshot_id = cur.lastrowid
            for d in detail:
                conn.execute(
                    "INSERT INTO cross_summary_table(snapshot_id, table_name, bytes) VALUES (?,?,?)",
                    (snapshot_id, d["table"], d["bytes"]),
                )
            # 同步旧 meta 灯位：只允许与快照同色，杜绝半修假绿。
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('cross_summary_chip', ?)",
                (chip,),
            )
            return {
                "snapshot_id": snapshot_id,
                "total_bytes": total,
                "tables": detail,
                "chip": chip,
                "aligned": aligned,
                "included": requested,
                "requested": requested,
                "missing_tables": missing,
            }


def latest_snapshot(db_path: str | None = None) -> dict | None:
    """读取最近一次快照；无快照返回 None，不触发生成、不造假绿。"""
    with get_db(db_path) as conn:
        head = conn.execute(
            "SELECT * FROM cross_summary_snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not head:
            return None
        rows = conn.execute(
            "SELECT table_name, bytes FROM cross_summary_table "
            "WHERE snapshot_id=? ORDER BY id",
            (head["id"],),
        ).fetchall()
        detail = [{"table": r["table_name"], "bytes": int(r["bytes"])} for r in rows]
        missing = json.loads(head["missing_tables"] or "[]")

        # 读时再校验：库里现状若已漂移（新表未纳入 / 字节变化），快照即时转红并点名。
        live_tables = _read_live_tables(conn)
        live_bytes = {d["table"]: d["bytes"] for d in _read_table_bytes(conn, sorted(live_tables))}
        snap_bytes = {d["table"]: d["bytes"] for d in detail}
        drift_tables = sorted(tb for tb in live_bytes if live_bytes[tb] != snap_bytes.get(tb))
        extra_missing = sorted(live_tables - set(snap_bytes))
        all_missing = sorted(set(missing) | set(extra_missing))
        aligned = (not all_missing) and (not drift_tables) and head["aligned"] == 1
        chip = GREEN if aligned else RED
        return {
            "snapshot_id": head["id"],
            "total_bytes": int(head["total_bytes"]),
            "tables": detail,
            "chip": chip,
            "aligned": aligned,
            "included": [d["table"] for d in detail],
            "requested": [d["table"] for d in detail],
            "missing_tables": all_missing,
            "drift_tables": drift_tables,
            "created_at": head["created_at"],
        }


def current_chip(db_path: str | None = None) -> dict:
    """四个页面共用的灯色来源；无快照时不是绿灯。"""
    snap = latest_snapshot(db_path)
    if snap is None:
        with get_db(db_path) as conn:
            live = sorted(r["table_name"] for r in conn.execute(
                "SELECT DISTINCT table_name FROM lake_files"
            ).fetchall())
        return {
            "chip": RED,
            "aligned": False,
            "missing_tables": live,
            "has_snapshot": False,
        }
    snap["has_snapshot"] = True
    return snap
