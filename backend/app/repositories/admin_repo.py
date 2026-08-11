"""admin_audit 表数据访问。"""
from sqlalchemy.orm import Session

from app.models.db_models import AdminAudit


class AdminRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def log_action(self, action: str) -> None:
        self._s.add(AdminAudit(action=action))
        self._s.flush()
