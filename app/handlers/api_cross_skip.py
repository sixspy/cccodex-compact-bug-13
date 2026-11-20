from app.handlers.base import BaseHandler
from app.services.cross_skip_ledger import append_ledger, dashboard
from app.services.cross_skip_surface import reconcile_surface, snapshot


class ApiCrossSkipDash(BaseHandler):
    def get(self):
        self.require_user()
        self.json(dashboard())


class ApiCrossSkipNote(BaseHandler):
    def post(self):
        self.require_user()
        body = self.read_json()
        self.json(
            append_ledger(
                int(body.get("plan_id") or 0),
                str(body.get("note") or "跨表漏计"),
            )
        )


class ApiCrossSkipHalf(BaseHandler):
    def post(self):
        self.require_user()
        self.json(reconcile_surface())


class ApiCrossSkipSnap(BaseHandler):
    def get(self):
        self.require_user()
        self.json(snapshot())
