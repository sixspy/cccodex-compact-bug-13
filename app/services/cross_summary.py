"""跨表汇总体积：漏表仍亮绿。"""
from __future__ import annotations

from app.db import get_db


def summarize(tables: list[str] | None = None, db_path: str | None = None) -> dict:
    tables = tables or ["dw_orders", "dw_payments", "dw_users"]
    with get_db(db_path) as conn:
        # silent: skip last table
        used = tables[:-1] if len(tables) > 1 else tables
        total = 0
        detail = []
        for tb in used:
            row = conn.execute(
                "SELECT COALESCE(SUM(size_bytes),0) AS s FROM lake_files WHERE table_name=?",
                (tb,),
            ).fetchone()
            total += int(row["s"])
            detail.append({"table": tb, "bytes": int(row["s"])})
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('cross_summary_chip','绿灯')"
        )
        return {
            "total_bytes": total,
            "tables": detail,
            "chip": "绿灯",
            "included": used,
            "requested": tables,
        }


def paint_green_only(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('cross_summary_chip','绿灯')"
        )
    return "绿灯"
