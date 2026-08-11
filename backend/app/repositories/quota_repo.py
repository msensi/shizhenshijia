"""search_quota_daily 表数据访问：原子扣减（SPEC 11 防配额穿透）。

SQLite 下用 UPDATE ... WHERE 条件更新实现原子扣减：只有未超限时才 +1，
受影响行数 0 即表示当日额度已尽。不能"先查后写"——并发下会穿透。
"""
from datetime import date

from sqlalchemy import insert, update
from sqlalchemy.orm import Session

from app.models.db_models import SearchQuotaDaily


class QuotaRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def _ensure_row(self, day: date) -> None:
        existing = self._s.get(SearchQuotaDaily, day)
        if existing is None:
            try:
                self._s.execute(
                    insert(SearchQuotaDaily).values(date=day, search_calls=0, total_cost_fen=0)
                )
                self._s.flush()
            except Exception:
                self._s.rollback()  # 并发插入冲突：行已存在即可

    def try_consume(self, day: date, max_calls: int, max_cost_fen: int, cost_fen: int) -> bool:
        """原子扣减一次搜索调用额度。成功返回 True，触顶返回 False。"""
        self._ensure_row(day)
        stmt = (
            update(SearchQuotaDaily)
            .where(
                SearchQuotaDaily.date == day,
                SearchQuotaDaily.search_calls < max_calls,
                SearchQuotaDaily.total_cost_fen + cost_fen <= max_cost_fen,
            )
            .values(
                search_calls=SearchQuotaDaily.search_calls + 1,
                total_cost_fen=SearchQuotaDaily.total_cost_fen + cost_fen,
            )
        )
        result = self._s.execute(stmt)
        self._s.flush()
        return result.rowcount == 1

    def get_today(self, day: date) -> SearchQuotaDaily | None:
        return self._s.get(SearchQuotaDaily, day)

    def is_exhausted(self, day: date, max_calls: int, max_cost_fen: int) -> bool:
        row = self.get_today(day)
        if row is None:
            return False
        return row.search_calls >= max_calls or row.total_cost_fen >= max_cost_fen

    def peek(self, day: date) -> tuple[int, int]:
        row = self._s.get(SearchQuotaDaily, day)
        if row is None:
            return 0, 0
        return row.search_calls, row.total_cost_fen
