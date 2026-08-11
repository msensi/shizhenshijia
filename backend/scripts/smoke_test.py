"""阶段 A 生死关卡：千问 json_object 字段级 Schema 遵循冒烟测试。

做法：读 .env 的 LLM_API_KEY，程序生成一张带文字的测试图，对
claim-v1 / scope-v1 / evidence-v1 三个契约各做 N 次真实调用，
用程序侧同一套 Pydantic 解析器统计字段级通过率（含程序纠偏前后）。

用法：
    cd backend && python scripts/smoke_test.py [--runs 3]

无 LLM_API_KEY 时：输出 SKIP 并以 0 退出（不阻塞 CI），但报告中醒目标注
"未经实 key 验证"——上线前必须用真实 key 跑一次。
"""
from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.pipeline.prompts import (  # noqa: E402
    CLAIM_PROMPT,
    CLAIM_SCHEMA_HINT,
    EVIDENCE_SCHEMA_HINT,
    SCOPE_PROMPT,
    SCOPE_SCHEMA_HINT,
    build_evidence_prompt,
)
from app.providers.dashscope_llm import DashScopeLLMAdapter  # noqa: E402
from app.schemas.claim import parse_claim_v1  # noqa: E402
from app.schemas.evidence import parse_evidence_v1  # noqa: E402
from app.schemas.scope import parse_scope_v1  # noqa: E402

SAMPLE_CLAIM = "高血压患者血压正常后可以停用降压药"
SAMPLE_SOURCE = (
    "高血压患者即使血压恢复正常，也不应自行停用降压药。"
    "血压正常是药物控制的结果，擅自停药会导致血压反弹，"
    "增加心梗、脑卒中等风险。是否调整用药需由医生评估决定。"
)


# 探测可用的中文字体（PIL 默认字体不含 CJK 字形，画中文会变方块导致模型判 unreadable）
_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def _load_cjk_font(size: int):
    for path in _CJK_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return None  # 无 CJK 字体时退化默认字体（英文环境）


def make_test_image() -> bytes:
    """程序生成带文字的测试图（健康谣言话术 + 角落诱饵，覆盖降权场景）。"""
    img = Image.new("RGB", (800, 600), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    f_big = _load_cjk_font(44)
    f_mid = _load_cjk_font(34)
    f_small = _load_cjk_font(24)
    draw.text((60, 80), "重大通知：血压正常后就可以停药了", fill=(20, 20, 20), font=f_big)
    draw.text((60, 170), "转发给身边有高血压的亲人", fill=(20, 20, 20), font=f_mid)
    draw.text((60, 250), "今天最后一天，错过再等一年", fill=(160, 30, 30), font=f_mid)
    draw.text((560, 530), "扫码进群领红包", fill=(120, 120, 120), font=f_small)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def check_claim(payload: dict) -> list[str]:
    """字段级检查（对照程序解析器的纠偏结果逐项验收）。"""
    issues: list[str] = []
    doc = parse_claim_v1(payload)
    if doc.image_readability.value not in ("clear", "partial", "unreadable"):
        issues.append("image_readability 枚举越界")
    if not doc.candidates:
        issues.append("candidates 为空或全部被程序校验剔除")
    for c in doc.candidates:
        if not c.quote_from_image.strip():
            issues.append(f"候选 {c.id} quote_from_image 为空")
        raw = next((x for x in payload.get("candidates", []) if x.get("id") == c.id), {})
        if "is_visual_main_subject" not in raw:
            issues.append(f"候选 {c.id} 缺 is_visual_main_subject 字段（程序已按 false 纠偏）")
        if "visual_prominence" not in raw:
            issues.append(f"候选 {c.id} 缺 visual_prominence 字段")
        try:
            from app.schemas.claim import ActionType
            ActionType(raw.get("action_type", "none"))
        except ValueError:
            issues.append(f"候选 {c.id} action_type 枚举越界: {raw.get('action_type')}")
    return issues


def check_scope(payload: dict) -> list[str]:
    issues: list[str] = []
    doc = parse_scope_v1(payload)
    if doc.scope_status.value not in ("in_scope", "out_of_scope", "insufficient_information"):
        issues.append("scope_status 枚举越界")
    raw_status = payload.get("scope_status")
    if raw_status != doc.scope_status.value:
        issues.append(f"scope_status 原始值非法被纠偏: {raw_status}")
    if payload.get("domain") not in ("health", "policy", "scam", "news", "non_factual", "out_of_scope"):
        issues.append(f"domain 枚举越界: {payload.get('domain')}")
    if raw_status == "in_scope" and payload.get("domain") == "health" and not payload.get("rule_id"):
        issues.append("in_scope 但缺 rule_id")
    return issues


def check_evidence(payload: dict) -> list[str]:
    issues: list[str] = []
    doc = parse_evidence_v1(payload)
    if payload.get("claim_relation") not in (
        "direct_support", "direct_refute", "mixed", "related_only", "not_related", "cannot_determine"
    ):
        issues.append(f"claim_relation 枚举越界: {payload.get('claim_relation')}")
    if payload.get("time_status") not in ("valid", "outdated", "unknown"):
        issues.append(f"time_status 枚举越界: {payload.get('time_status')}")
    quote = doc.supporting_quote.strip()
    if quote and quote not in SAMPLE_SOURCE:
        issues.append("supporting_quote 无法回溯到来源原文（编造风险）")
    if doc.claim_relation.value in ("direct_support", "direct_refute") and not quote:
        issues.append("直接支持/反驳但缺 supporting_quote")
    return issues


async def run_once(llm: DashScopeLLMAdapter, image: bytes) -> dict:
    report: dict = {"schemas": {}}

    vision = await llm.vision_json(image, CLAIM_PROMPT, CLAIM_SCHEMA_HINT)
    report["schemas"]["claim-v1"] = _eval(vision, check_claim)

    scope_prompt = (
        f"{SCOPE_PROMPT}\n\nclaim_id：c1\n待判断说法：{SAMPLE_CLAIM}\n"
        f"图片原文：血压正常后就可以停药\n画面真实性存疑：false"
    )
    scope = await llm.text_json(scope_prompt, SCOPE_SCHEMA_HINT)
    report["schemas"]["scope-v1"] = _eval(scope, check_scope)

    ev_prompt = build_evidence_prompt(
        SAMPLE_CLAIM, "高血压患者能否自行停药（国家卫健委科普）",
        SAMPLE_SOURCE, "knowledge_base", "nhc-2025-001",
    )
    evidence = await llm.text_json(ev_prompt, EVIDENCE_SCHEMA_HINT)
    report["schemas"]["evidence-v1"] = _eval(evidence, check_evidence)
    return report


def _eval(result, checker) -> dict:
    if result.config_invalid:
        return {"outcome": "CONFIG_INVALID", "issues": [result.error]}
    if not result.ok or result.payload is None:
        return {"outcome": "FAIL", "issues": [result.error or "non-json output"]}
    issues = checker(result.payload)
    return {"outcome": "PASS" if not issues else "ISSUES", "issues": issues,
            "latency_ms": result.latency_ms}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    settings = get_settings()
    print("=" * 60)
    print("冒烟测试：千问 json_object 字段级 Schema 遵循率")
    print(f"视觉模型: {settings.vision_model} / 文本模型: {settings.text_model}")
    print(f"temperature={settings.llm_temperature}（锁定）")
    print("=" * 60)

    if not settings.llm_api_key:
        print("SKIP: LLM_API_KEY 未配置。请在 backend/.env 填入真实 key 后重跑")
        print("警告：Schema 遵循率未经实 key 验证，上线前此为阻塞项（SPEC 11 内嵌坑）")
        return 0

    llm = DashScopeLLMAdapter(settings)
    image = make_test_image()

    tally: dict[str, dict[str, int]] = {}
    all_issues: dict[str, list[str]] = {}
    for i in range(args.runs):
        print(f"\n--- 第 {i + 1}/{args.runs} 轮 ---")
        report = await run_once(llm, image)
        for schema, r in report["schemas"].items():
            t = tally.setdefault(schema, {"PASS": 0, "ISSUES": 0, "FAIL": 0, "CONFIG_INVALID": 0})
            t[r["outcome"]] = t.get(r["outcome"], 0) + 1
            for issue in r["issues"]:
                all_issues.setdefault(schema, []).append(issue)
            print(f"  {schema}: {r['outcome']}  issues={r['issues'] or '无'}")

    print("\n" + "=" * 60)
    print("通过率汇总")
    total_pass = True
    for schema, t in tally.items():
        n = sum(t.values())
        strict = t.get("PASS", 0)
        print(f"  {schema}: 严格通过 {strict}/{n}  "
              f"(ISSUES={t.get('ISSUES', 0)} FAIL={t.get('FAIL', 0)} CONFIG_INVALID={t.get('CONFIG_INVALID', 0)})")
        if t.get("FAIL", 0) > 0 or t.get("CONFIG_INVALID", 0) > 0:
            total_pass = False

    if all_issues:
        print("\n字段级问题与 prompt 修正建议：")
        for schema, issues in all_issues.items():
            uniq = sorted(set(issues))
            print(f"  [{schema}]")
            for issue in uniq:
                print(f"    - {issue}")
            print(f"    建议：在 {schema} 的 schema_hint 中对该字段加粗强调必填与枚举全集，"
                  f"并在 prompt 中追加反面示例；程序侧 Pydantic 纠偏已兜底，"
                  f"但遵循率低会放大幻觉风险")
    print("=" * 60)
    verdict = "PASS（字段级全通过）" if total_pass and not all_issues else \
              ("PASS_WITH_ISSUES（程序纠偏兜底可用，建议按上方修正 prompt）" if total_pass else "FAIL（存在硬失败，阻塞阶段 A）")
    print(f"结论: {verdict}")
    return 0 if total_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
