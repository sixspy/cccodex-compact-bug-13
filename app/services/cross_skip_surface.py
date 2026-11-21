"""跨表漏计：展示面与写库面统一到独立快照表，半修只碰展示的旧路已废。

本模块不再向 meta 写任何灯色；灯色唯一来源是 cross_summary 的快照。
任何“只刷绿灯”的动作都拿不到绿色——没有纳入清单的快照即为漏表汇总（红）。
"""
from __future__ import annotations

from app.services import cross_summary

_SLUG = "cross_skip"
_OK = "绿灯"
_BAD = "漏表汇总"


def panel_chip(db_path: str | None = None) -> str:
    return cross_summary.current_chip(db_path)["chip"]


def truth_flag(db_path: str | None = None) -> str:
    # 展示面与真相同源，不再允许双源假绿。
    return cross_summary.current_chip(db_path)["chip"]


def paint_ok(db_path: str | None = None) -> str:
    # 半修入口：禁止脱离纳入清单单独写绿，返回真实灯色。
    return cross_summary.current_chip(db_path)["chip"]


def seed_skew(db_path: str | None = None) -> None:
    # 旧版在此种“面板绿/真相红”的歪斜数据，补洞后不再种假绿。
    return None


def bump_counter(db_path: str | None = None) -> int:
    # 仅保留事件计数，不再顺带把面板刷绿。
    from app.db import get_db

    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key=?",
            (f"{_SLUG}_counter",),
        ).fetchone()
        n = int(row["value"]) + 1 if row else 1
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (f"{_SLUG}_counter", str(n)),
        )
        return n


def snapshot(db_path: str | None = None) -> dict:
    chip = cross_summary.current_chip(db_path)
    return {
        "title": "跨表漏计",
        "panel_chip": chip["chip"],
        "truth": chip["chip"],
        "counter": bump_counter(db_path),
        "aligned": bool(chip["aligned"]),
        "missing_tables": chip.get("missing_tables", []),
    }


def list_events(db_path: str | None = None) -> list[dict]:
    from app.db import get_db

    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_evt_%",),
        ).fetchall()
        return [{"note": r["value"]} for r in rows]


def record_event(note: str, db_path: str | None = None) -> dict:
    from app.db import get_db

    with get_db(db_path) as conn:
        c = bump_counter(db_path)
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (f"{_SLUG}_evt_{c}", note or _BAD),
        )
    return snapshot(db_path)


def reconcile_surface(db_path: str | None = None) -> dict:
    # “半修对齐”按钮的旧行为是只刷展示面；现在拒绝假绿，返回快照真实状态。
    chip = cross_summary.current_chip(db_path)
    return {
        "panel_chip": chip["chip"],
        "truth": chip["chip"],
        "half_fixed": False,
        "missing_tables": chip.get("missing_tables", []),
    }
