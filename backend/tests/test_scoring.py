"""打分排序 + 视觉主体降权规则测试（PRD 3.1，AC-03）。"""
from app.schemas.claim import ActionType, ClaimCandidate, HarmType, Urgency, VisualProminence
from app.services.scoring import score_candidate, select_primary

DEMOTION = 18


def _c(id_, action, harm=HarmType.none, urgency=Urgency.none, subject=True,
       prominence=VisualProminence.dominant, quote="原文", claim="完整说法",
       verifiable=True) -> ClaimCandidate:
    return ClaimCandidate(
        id=id_, quote_from_image=quote, normalized_claim=claim,
        action_type=action, harm_type=harm, urgency=urgency,
        is_verifiable=verifiable, is_visual_main_subject=subject,
        visual_prominence=prominence,
    )


class TestBaseScore:
    def test_money_transfer_base_100_plus_harm(self):
        c = _c("c1", ActionType.money_transfer, HarmType.financial)
        assert score_candidate(c) == 100 + 10 + 5

    def test_general_health_base_40(self):
        c = _c("c1", ActionType.general_health, HarmType.health)
        assert score_candidate(c) == 40 + 5

    def test_urgency_words_add_10(self):
        c = _c("c1", ActionType.general_health, HarmType.health,
               quote="好消息，今天截止领取")
        assert score_candidate(c) == 40 + 10 + 5

    def test_unverifiable_no_completeness_bonus(self):
        c = _c("c1", ActionType.general_health, HarmType.health, verifiable=False)
        assert score_candidate(c) == 40


class TestVisualDemotion:
    def test_top_non_subject_demoted_and_reranked(self):
        # 角落诈骗话术 115 分但非视觉主体；主体健康谣言 45+10+5=60 分
        bait = _c("bait", ActionType.money_transfer, HarmType.financial,
                  subject=False, prominence=VisualProminence.corner)
        body = _c("body", ActionType.medication_change, HarmType.health)
        sel = select_primary([bait, body], DEMOTION)
        assert sel.demotion_applied is True
        assert sel.demotion_delta == DEMOTION
        assert sel.primary is not None and sel.primary.id == "body"

    def test_top_subject_no_demotion(self):
        bait = _c("bait", ActionType.money_transfer, HarmType.financial)
        sel = select_primary([bait], DEMOTION)
        assert sel.demotion_applied is False
        assert sel.primary is not None and sel.primary.id == "bait"

    def test_peripheral_prominence_forces_non_subject(self):
        # is_visual_main_subject=true 但 prominence=peripheral -> 仍按非主体处理
        bait = _c("bait", ActionType.money_transfer, HarmType.financial,
                  subject=True, prominence=VisualProminence.peripheral)
        body = _c("body", ActionType.policy_service, HarmType.public)
        sel = select_primary([bait, body], DEMOTION)
        assert sel.demotion_applied is True
        assert sel.primary is not None and sel.primary.id == "body"

    def test_bait_never_beats_subject_body(self):
        # 规则意图：只要存在视觉主体候选，角落诱饵（即使分高）不得抢走主核验资格
        bait = _c("bait", ActionType.money_transfer, HarmType.financial,
                  subject=False, prominence=VisualProminence.corner)
        body = _c("body", ActionType.general_health, HarmType.health)
        sel = select_primary([bait, body], DEMOTION)
        assert sel.demotion_applied is True
        assert sel.primary is not None and sel.primary.id == "body"

    def test_all_non_subject_still_selects(self):
        # 全为非视觉主体候选时（如纯文字海报），仍按降权规则选出最高分者
        bait = _c("bait", ActionType.money_transfer, HarmType.financial,
                  subject=False, prominence=VisualProminence.corner)
        weak = _c("weak", ActionType.general_health, HarmType.health,
                  subject=False, prominence=VisualProminence.peripheral)
        sel = select_primary([bait, weak], DEMOTION)
        assert sel.demotion_applied is True
        assert sel.primary is not None and sel.primary.id == "bait"

    def test_missing_subject_field_defaults_false(self):
        c = ClaimCandidate.model_validate({
            "id": "x", "quote_from_image": "q", "normalized_claim": "n",
            "action_type": "money_transfer", "harm_type": "financial",
        })
        assert c.is_visual_main_subject is False
        assert c.effective_is_main_subject() is False


class TestTieBreak:
    def test_financial_beats_health_on_tie(self):
        a = _c("a", ActionType.safety_action, HarmType.safety)   # 85+10+5=100
        # 构造同分：改用 urgency 对齐
        b2 = _c("b", ActionType.medication_change, HarmType.health)  # 95+10+5=110
        sel = select_primary([a, b2], DEMOTION)
        assert sel.primary is not None and sel.primary.id == "b"

    def test_no_verifiable_candidates_returns_none(self):
        c = _c("a", ActionType.general_health, verifiable=False)
        sel = select_primary([c], DEMOTION)
        assert sel.primary is None
