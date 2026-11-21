"""compact-bug-13 核验：跨表漏表假绿 / 对账假过 / 落库污染。

库表侧直查快照表，页面侧走 HTTP，两侧都要过。
"""
import json
import threading

import pytest
import tornado.testing
import tornado.web

from app.config import Config
from app.db import get_db
from app.handlers.base import serializer
from app.main import make_app
from app.seed import reset_seed
from app.services import cross_summary as cs
from app.services import files, plans, reconcile, rewrite
from app.services.errors import ServiceError

ALL_TABLES = ["dw_orders", "dw_payments", "dw_users"]
# 种子数据各表字节。
TRUTH = {"dw_orders": 1_310_000, "dw_payments": 595_000, "dw_users": 585_000}
TRUTH_TOTAL = sum(TRUTH.values())


# ---------- 库表侧：独立快照单轨 ----------

def test_no_snapshot_never_green(db):
    chip = cs.current_chip(db_path=db)
    assert chip["chip"] == "漏表汇总"
    assert chip["has_snapshot"] is False
    assert set(chip["missing_tables"]) == set(ALL_TABLES)


def test_full_snapshot_green_and_records_included_list(db):
    out = cs.summarize(db_path=db)
    assert out["chip"] == "绿灯"
    assert out["total_bytes"] == TRUTH_TOTAL
    assert out["missing_tables"] == []
    # 快照头落库
    with get_db(db) as conn:
        head = conn.execute(
            "SELECT * FROM cross_summary_snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert head["chip"] == "绿灯"
        assert head["aligned"] == 1
        assert head["included_count"] == 3
        rows = conn.execute(
            "SELECT table_name, bytes FROM cross_summary_table WHERE snapshot_id=?",
            (head["id"],),
        ).fetchall()
        got = {r["table_name"]: r["bytes"] for r in rows}
        assert got == TRUTH
        # 逐表字节之和必须与汇总头对齐
        assert sum(r["bytes"] for r in rows) == head["total_bytes"]
        assert json.loads(head["missing_tables"]) == []


def test_missing_table_is_red_and_names_missing(db):
    # 只汇总两张表，漏 dw_users
    out = cs.summarize(["dw_orders", "dw_payments"], db_path=db)
    assert out["chip"] == "漏表汇总"
    assert out["missing_tables"] == ["dw_users"]
    assert out["total_bytes"] == TRUTH["dw_orders"] + TRUTH["dw_payments"]
    # 页面/列表共用灯色同样为红，并点名
    chip = cs.current_chip(db_path=db)
    assert chip["chip"] == "漏表汇总"
    assert chip["missing_tables"] == ["dw_users"]
    with get_db(db) as conn:
        head = conn.execute(
            "SELECT * FROM cross_summary_snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert head["chip"] == "漏表汇总"
        assert json.loads(head["missing_tables"]) == ["dw_users"]
        # 纳入清单确实只记了两张
        names = [
            r["table_name"]
            for r in conn.execute(
                "SELECT table_name FROM cross_summary_table WHERE snapshot_id=?",
                (head["id"],),
            ).fetchall()
        ]
        assert names == ["dw_orders", "dw_payments"]


def test_paint_green_only_path_is_dead(db):
    # 半修：只碰灯色不记纳入清单，必须拿不到绿灯
    from app.services.cross_skip_surface import (
        paint_ok,
        reconcile_surface,
        seed_skew,
    )

    seed_skew(db)  # 旧版种假绿的入口，现在应为空操作
    assert paint_ok(db) == "漏表汇总"
    half = reconcile_surface(db)
    assert half["panel_chip"] == "漏表汇总"
    assert half["truth"] == "漏表汇总"
    assert half["half_fixed"] is False
    with get_db(db) as conn:
        assert not conn.execute(
            "SELECT 1 FROM meta WHERE key='cross_skip_panel_chip'"
        ).fetchone()


def test_snapshot_drift_after_new_file_turns_red(db):
    cs.summarize(db_path=db)  # 先绿
    files.register_file("lake/dw_users/part-900.parquet", "dw_users", 12345, db_path=db)
    # 同一张快照读时再校验：字节漂移，转红并点名
    chip = cs.current_chip(db_path=db)
    assert chip["chip"] == "漏表汇总"
    assert "dw_users" in chip["drift_tables"]
    # 重新补洞后回绿
    again = cs.summarize(db_path=db)
    assert again["chip"] == "绿灯"
    assert again["total_bytes"] == TRUTH_TOTAL + 12345


def test_register_blocked_while_red_snapshot_open(db):
    cs.summarize(["dw_orders", "dw_payments"], db_path=db)  # 红快照（漏 dw_users）
    with pytest.raises(ServiceError) as ei:
        files.register_file("lake/dw_orders/part-77.parquet", "dw_orders", 1, db_path=db)
    assert "挡" in ei.value.message
    # 被挡后没有落库
    assert not files.list_files("dw_orders", db_path=db) or all(
        f["path"] != "lake/dw_orders/part-77.parquet"
        for f in files.list_files("dw_orders", db_path=db)
    )


def test_rewrite_queue_blocked_while_red(db):
    p = plans.create_plan("CP-RED", "红快照计划", "dw_payments", db_path=db)
    plans.attach_loose_files(p["id"], db_path=db)
    plans.publish_plan(p["id"], db_path=db)
    cs.summarize(["dw_orders", "dw_payments"], db_path=db)  # 漏 dw_users
    with pytest.raises(ServiceError) as ei:
        rewrite.start_rewrite(p["id"], db_path=db)
    assert "挡" in ei.value.message
    # 补洞回绿后放行
    cs.summarize(db_path=db)
    job = rewrite.start_rewrite(p["id"], db_path=db)
    assert job["status"] == "成功"
    assert job["merged_bytes"] == TRUTH["dw_payments"]


def test_concurrent_summarize_no_double_write_overwrite(db):
    errors = []

    def worker():
        try:
            for _ in range(5):
                cs.summarize(db_path=db)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert errors == []
    with get_db(db) as conn:
        # 10 次补洞 = 10 张快照，每张都有 3 行明细，无互相覆盖
        heads = conn.execute("SELECT COUNT(*) AS c FROM cross_summary_snapshot").fetchone()["c"]
        details = conn.execute("SELECT COUNT(*) AS c FROM cross_summary_table").fetchone()["c"]
        assert heads == 10
        assert details == 30
        bad = conn.execute(
            "SELECT s.id FROM cross_summary_snapshot s JOIN cross_summary_table t ON t.snapshot_id=s.id "
            "GROUP BY s.id HAVING SUM(t.bytes) != s.total_bytes"
        ).fetchall()
        assert bad == []
    assert cs.current_chip(db_path=db)["chip"] == "绿灯"


# ---------- 对账不假过 ----------

def test_reconcile_fails_when_no_success_job(db):
    p = plans.create_plan("CP-NOJOB", "无合并任务", "dw_users", db_path=db)
    plans.attach_loose_files(p["id"], db_path=db)
    plans.publish_plan(p["id"], db_path=db)
    report = reconcile.run_reconcile(p["id"], db_path=db)
    assert report["passed"] is False
    assert report["chip"] == "体积不符"
    assert "不通过" in report["summary"]


def test_reconcile_chain_still_passes(db):
    p = plans.create_plan("CP-OK", "链路计划", "dw_payments", db_path=db)
    plans.attach_loose_files(p["id"], db_path=db)
    plans.publish_plan(p["id"], db_path=db)
    cs.summarize(db_path=db)
    job = rewrite.start_rewrite(p["id"], db_path=db)
    assert job["merged_bytes"] == TRUTH["dw_payments"]
    report = reconcile.run_reconcile(p["id"], db_path=db)
    assert report["passed"] is True
    assert report["chip"] == "绿灯"


def test_reconcile_list_carries_real_cross_chip(db):
    cs.summarize(["dw_orders"], db_path=db)  # 红
    p = plans.create_plan("CP-LIST", "列表计划", "dw_users", db_path=db)
    plans.attach_loose_files(p["id"], db_path=db)
    plans.publish_plan(p["id"], db_path=db)
    reconcile.run_reconcile(p["id"], db_path=db)
    items = reconcile.list_reports_with_cross(db_path=db)
    assert items[0]["cross_chip"] == "漏表汇总"
    assert set(items[0]["cross_missing_tables"]) == {"dw_payments", "dw_users"}


# ---------- 页面侧：HTTP 接口 ----------

class HttpCase(tornado.testing.AsyncHTTPTestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "http.db")
        self._old_db = Config.DEFAULT_DB
        import os
        os.environ["DATABASE_PATH"] = self.db_path
        reset_seed(self.db_path)
        super().setUp()
        self.cookie = self._login()

    def tearDown(self):
        super().tearDown()
        self.tmp.cleanup()
        import os
        os.environ.pop("DATABASE_PATH", None)

    def get_app(self):
        return make_app()

    def _login(self):
        resp = self.fetch(
            "/api/login",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"username": "admin", "password": "123456"}),
        )
        assert resp.code == 200
        return resp.headers["Set-Cookie"].split(";")[0]

    def get(self, path):
        return self.fetch(path, headers={"Cookie": self.cookie})

    def post(self, path, body=None):
        return self.fetch(
            path,
            method="POST",
            headers={"Content-Type": "application/json", "Cookie": self.cookie},
            body=json.dumps(body or {}),
        )

    def test_chip_endpoint_red_before_snapshot(self):
        resp = self.get("/api/reconcile/cross-chip")
        data = json.loads(resp.body)
        assert data["chip"] == "漏表汇总"
        assert data["has_snapshot"] is False

    def test_build_snapshot_then_green(self):
        resp = self.post("/api/reconcile/cross-summary")
        data = json.loads(resp.body)["snapshot"]
        assert data["chip"] == "绿灯"
        assert data["total_bytes"] == TRUTH_TOTAL
        chip = json.loads(self.get("/api/reconcile/cross-chip").body)
        assert chip["chip"] == "绿灯"
        assert chip["missing_tables"] == []

    def test_partial_snapshot_red_and_named_over_http(self):
        resp = self.post(
            "/api/reconcile/cross-summary", {"tables": ["dw_orders", "dw_payments"]}
        )
        data = json.loads(resp.body)["snapshot"]
        assert resp.code == 200
        assert data["chip"] == "漏表汇总"
        assert data["missing_tables"] == ["dw_users"]
        # 对账列表接口同步为红并点名
        reports = json.loads(self.get("/api/reconcile/reports").body)["items"]
        if reports:
            assert reports[0]["cross_chip"] == "漏表汇总"

    def test_half_fix_endpoint_cannot_green(self):
        resp = self.post("/api/cross_skip/half")
        data = json.loads(resp.body)
        assert data["panel_chip"] == "漏表汇总"
        assert data["truth"] == "漏表汇总"
        dash = json.loads(self.get("/api/cross_skip/dash").body)
        assert dash["fake_green"] is False
        assert dash["chip"] == "漏表汇总"

    def test_rewrite_blocked_over_http_when_red(self):
        # 建计划、挂文件、发布
        self.post("/api/plans", {
            "plan_code": "CP-WEB", "title": "页面计划", "target_table": "dw_payments"
        })
        plan_id = json.loads(self.get("/api/plans").body)["items"][0]["id"]
        self.post(f"/api/plans/{plan_id}/attach")
        self.post(f"/api/plans/{plan_id}/publish")
        # 红快照
        self.post("/api/reconcile/cross-summary", {"tables": ["dw_orders"]})
        resp = self.post(f"/api/rewrite/plans/{plan_id}/start")
        assert resp.code == 400
        assert "挡" in json.loads(resp.body)["error"]

    def test_spa_page_served(self):
        from pathlib import Path

        resp = self.get("/app/")
        assert resp.code == 200
        html = resp.body.decode()
        assert "体积对账" in html
        # 四个页面的灯色都接真快照接口，且无硬编码绿灯残留
        pages = Path("/workspace/static/js/pages")
        for name in ("files.js", "plans.js", "rewrite.js", "reconcile.js", "settings.js"):
            text = (pages / name).read_text(encoding="utf-8")
            assert "cross-chip" in text
            assert ">绿灯<" not in text
