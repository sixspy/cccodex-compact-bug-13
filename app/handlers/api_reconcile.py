from app.handlers.base import BaseHandler
from app.services import reconcile as reconcile_svc
from app.services import cross_summary as cross_svc
from app.services.errors import ServiceError


class ApiReconcileReports(BaseHandler):
    def get(self):
        self.require_user()
        self.json({"items": reconcile_svc.list_reports_with_cross()})

    def post(self):
        self.require_user()
        body = self.read_json()
        plan_id = int(body.get("plan_id"))
        self.json({"report": reconcile_svc.run_reconcile(plan_id)})


class ApiCrossSummary(BaseHandler):
    def get(self):
        self.require_user()
        # 只读最近快照与灯色，绝不在读路径顺手造假绿。
        self.json(cross_svc.current_chip())

    def post(self):
        self.require_user()
        body = self.read_json()
        tables = body.get("tables")
        if tables is not None and not isinstance(tables, list):
            tables = None
        try:
            self.json({"snapshot": cross_svc.summarize(tables)})
        except ServiceError as exc:  # 补洞失败：事务已整体回滚，回短句
            self.json({"error": f"汇总补洞失败：{exc.message}"}, status=exc.status_code)


class ApiCrossChip(BaseHandler):
    def get(self):
        self.require_user()
        self.json(cross_svc.current_chip())

