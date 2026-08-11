"""主核验对象选择：PRD 3.1 打分规则 + 视觉主体降权（P0，程序强制执行）。

打分：7 级基础分 + 催促语 +10 + 严重伤害 +10 + 完整可检索 +5
同分裁决：资金/个人信息 > 医疗/身体安全 > 有操作指令 > 醒目文字 > 自上而下
降权：最高分候选 is_visual_main_subject=false -> 扣 VISUAL_DEMOTION_SCORE 后重排
"""
import re
from dataclasses import dataclass

from app.schemas.claim import ActionType, ClaimCandidate, HarmType, Urgency

BASE_SCORE: dict[ActionType, int] = {
    ActionType.money_transfer: 100,
    ActionType.credential_request: 100,
    ActionType.medication_change: 95,
    ActionType.medical_treatment: 95,
    ActionType.safety_action: 85,
    ActionType.policy_service: 80,
    ActionType.purchase: 75,
    ActionType.public_event: 55,
    ActionType.general_health: 40,
    ActionType.none: 0,
}

URGENCY_WORDS = re.compile(r"立即|马上|限时|今天截止|最后一天|最后机会|过期不候|抓紧|速领|紧急")

# 同分裁决优先级：harm 类别 -> 操作指令 -> 顺序
_HARM_RANK = {
    HarmType.financial: 0,
    HarmType.privacy: 0,
    HarmType.health: 1,
    HarmType.safety: 1,
    HarmType.public: 2,
    HarmType.none: 3,
}


@dataclass
class ScoredCandidate:
    candidate: ClaimCandidate
    base_score: int
    final_score: int
    demoted: bool
    order_index: int  # 图片从上至下顺序


@dataclass
class SelectionResult:
    primary: ClaimCandidate | None
    ranked: list[ScoredCandidate]
    demotion_applied: bool
    demotion_delta: int


def score_candidate(c: ClaimCandidate) -> int:
    score = BASE_SCORE.get(c.action_type, 0)
    text = f"{c.quote_from_image} {c.normalized_claim}"
    if c.urgency is Urgency.high or URGENCY_WORDS.search(text):
        score += 10
    if c.harm_type in (HarmType.financial, HarmType.privacy, HarmType.health, HarmType.safety):
        # 涉及严重伤害或不可逆损失
        if c.action_type in (
            ActionType.money_transfer,
            ActionType.credential_request,
            ActionType.medication_change,
            ActionType.medical_treatment,
            ActionType.safety_action,
        ):
            score += 10
    if c.is_verifiable and c.normalized_claim.strip() and c.quote_from_image.strip():
        score += 5
    if c.action_type is ActionType.public_event:
        # 同一张图里“多部门行动”这类概括标题常与正文并存；优先核验带地点、时间、机构的那条。
        score += min(10, 2 * len(c.event_anchors.all_items()))
    return score


def _tie_rank(sc: ScoredCandidate) -> tuple:
    c = sc.candidate
    has_instruction = c.action_type is not ActionType.none
    return (_HARM_RANK.get(c.harm_type, 3), 0 if has_instruction else 1, sc.order_index)


def select_primary(
    candidates: list[ClaimCandidate], demotion_score: int
) -> SelectionResult:
    """选出唯一主核验对象。无可核验候选时 primary=None（不联网）。"""
    verifiable = [c for c in candidates if c.is_verifiable and c.quote_from_image.strip()]
    if not verifiable:
        return SelectionResult(None, [], False, 0)

    scored = [
        ScoredCandidate(c, score_candidate(c), 0, False, i)
        for i, c in enumerate(verifiable)
    ]
    for sc in scored:
        sc.final_score = sc.base_score

    # 视觉主体降权（PRD 3.1 P0，程序强制执行）：存在视觉主体候选时，凡得分达到
    # 主体最高分的非主体候选（即"与主体竞争主核验资格"的诱饵）一律扣分，直到
    # 不再压过任何主体候选为止；全是非主体候选时只对最高分执行一次降权。
    demotion_applied = False
    demotion_delta = 0
    subjects = [sc for sc in scored if sc.candidate.effective_is_main_subject()]
    non_subjects = [sc for sc in scored if not sc.candidate.effective_is_main_subject()]
    if subjects and non_subjects:
        bar = max(sc.final_score for sc in subjects)
        for sc in non_subjects:
            if sc.final_score >= bar:
                sc.final_score = bar - 1  # 压到主体之下，保证主体优先
                sc.demoted = True
                demotion_applied = True
                demotion_delta = demotion_score
    elif non_subjects and not subjects:
        top = max(non_subjects, key=lambda sc: sc.final_score)
        top.final_score -= demotion_score
        top.demoted = True
        demotion_applied = True
        demotion_delta = demotion_score

    ranked = sorted(scored, key=lambda sc: (-sc.final_score, _tie_rank(sc)))
    return SelectionResult(ranked[0].candidate, ranked, demotion_applied, demotion_delta)
