"""搜索预算控制测试（AC-11）：单次 <=3 计数器 + 日配额原子扣减熔断。"""
from datetime import date

import pytest

from app.pipeline.budget import BudgetController, PerAnalysisBudgetExceeded
from app.repositories.quota_repo import QuotaRepository


class TestPerAnalysisBudget:
    def test_max_3_calls(self, session, settings):
        ctrl = BudgetController(settings)
        budget = ctrl.new_budget(session)
        assert settings.search_max_calls_per_analysis == 3
        for _ in range(3):
            ctrl.consume_or_raise(session, budget)
        assert budget.calls_used == 3
        with pytest.raises(PerAnalysisBudgetExceeded):
            ctrl.consume_or_raise(session, budget)

    def test_quota_exhausted_blocks_all_calls(self, session, settings):
        repo = QuotaRepository(session)
        repo.try_consume(date.today(), 1, 10_000, 1)  # 人为顶到 1 次上限
        ctrl = BudgetController(settings)
        ctrl._s = settings.model_copy(update={"search_daily_quota": 1})
        budget = ctrl.new_budget(session)
        assert budget.quota_exhausted is True
        assert budget.can_call() is False


class TestDailyQuotaAtomic:
    def test_atomic_consume_stops_at_limit(self, session):
        repo = QuotaRepository(session)
        assert repo.try_consume(date.today(), 2, 10_000, 4) is True
        assert repo.try_consume(date.today(), 2, 10_000, 4) is True
        assert repo.try_consume(date.today(), 2, 10_000, 4) is False  # 第 3 次被拒

    def test_cost_limit_blocks(self, session):
        repo = QuotaRepository(session)
        assert repo.try_consume(date.today(), 100, 10, 6) is True
        assert repo.try_consume(date.today(), 100, 10, 6) is False  # 6+6>10

    def test_concurrent_consume_no_overrun(self, session):
        # 原子扣减：超限请求全部失败，不会出现穿透
        repo = QuotaRepository(session)
        results = [repo.try_consume(date.today(), 1, 10_000, 4) for _ in range(5)]
        assert results.count(True) == 1
        calls, cost = repo.peek(date.today())
        assert calls == 1 and cost == 4
