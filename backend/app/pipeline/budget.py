"""搜索预算控制：单次计数器 + 日配额原子扣减（SPEC AC-11）。

- 单次核验搜索调用 <= SEARCH_MAX_CALLS_PER_ANALYSIS（默认 3）
- 日配额：SEARCH_DAILY_QUOTA 次 / SEARCH_DAILY_COST_LIMIT_FEN 分，触顶熔断
- 扣减必须发生在调用前（防穿透），由 QuotaRepository.try_consume 原子完成
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.quota_repo import QuotaRepository


class PerAnalysisBudgetExceeded(Exception):
    pass


@dataclass
class SearchBudget:
    """一次核验任务级预算计数器。"""

    max_calls: int
    calls_used: int = 0
    quota_exhausted: bool = False  # 日额度触顶（进入降级路径）

    def remaining(self) -> int:
        return max(0, self.max_calls - self.calls_used)

    def can_call(self) -> bool:
        return self.calls_used < self.max_calls and not self.quota_exhausted


class BudgetController:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def new_budget(self, session: Session) -> SearchBudget:
        """开工时检查日额度：触顶则本次任务全程禁止联网搜索。"""
        repo = QuotaRepository(session)
        exhausted = repo.is_exhausted(
            date.today(),
            self._s.search_daily_quota,
            self._s.search_daily_cost_limit_fen,
        )
        return SearchBudget(
            max_calls=self._s.search_max_calls_per_analysis, quota_exhausted=exhausted
        )

    def consume_or_raise(self, session: Session, budget: SearchBudget) -> None:
        """调用前原子扣减。单次超限或日额度触顶都会拦下。"""
        if not budget.can_call():
            raise PerAnalysisBudgetExceeded()
        repo = QuotaRepository(session)
        ok = repo.try_consume(
            date.today(),
            self._s.search_daily_quota,
            self._s.search_daily_cost_limit_fen,
            self._s.search_cost_per_call_fen,
        )
        if not ok:
            budget.quota_exhausted = True
            raise PerAnalysisBudgetExceeded()
        budget.calls_used += 1
