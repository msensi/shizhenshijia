"""模型提示词与 Schema 提示。版本化，改动后必须重跑测试集（PRD 11.2）。

规则：立场词由程序模板写死，模型只提取/判断，不生成面向用户的文案。
"""

PROMPT_VERSION = "2026-08-08.v5"

CLAIM_PROMPT = """你是图片信息提取器。仔细看这张图，提取其中所有"用户看了可能照做"的说法（最多 3 条）。
要求：
1. quote_from_image 必须是图片里真实出现的原文文字，不得编造
2. normalized_claim 把口语补全成完整可核验的陈述句
3. action_type / harm_type / urgency 从给定枚举中选
4. is_visual_main_subject：判断这条文字是否是图片的视觉主体（按字号、版面位置、面积占比综合判断）；角落小字、边栏诱饵话术（如"扫码进群""领红包"）应判 false
5. visual_prominence：dominant=整版主体 / prominent=显著但非主体 / peripheral=边缘 / corner=角落
6. visual_authenticity_question：用户是否明显是在问画面中的事件是否真的发生。只要主体是奇闻、灾害、公共事件或疑似 AI/特效/影视/旧素材画面，就填 true；同时必须把“画面声称发生的事件”提取成一条可核验候选，例如“某地天空出现一条真实的龙”。不得仅凭单张截图断言画面由 AI 生成
7. 图片看不清时 image_readability 填 partial 或 unreadable
8. is_verifiable：这条说法是否能用事实证据判断真假。健康疗效、政策补贴、中奖转账、公共事件等"可以被权威来源证实或证伪"的具体陈述，一律填 true；只有纯口号、祝福、无事实内容的感叹（如"祝大家健康""太划算了"）才填 false。
   示例：养老金上调通知、某地补贴政策、某药疗效、中奖领钱 -> true；"错过再等一年""赶紧转发"这类无事实内容的催促 -> false
9. 禁止输出对图片本身的描述性总结作为候选（如"该图片内容为一份关于补贴的通知""这是一张保健品广告"）——候选必须是图片里可直接引用的具体说法。如果图片模糊到只能看出"大概是某类通知"而读不出具体文字，image_readability 必须填 partial 或 unreadable，且不要编造候选；读不出任何完整句子时 candidates 留空
10. action_type=public_event 时，必须从整张图中补齐 event_anchors：能读到的日期、城市/具体地点、执法或发布机构、涉事物、账号名称都要逐字填写。normalized_claim 不得省略这些专有细节；看不清的字段留空，不能猜测"""

CLAIM_SCHEMA_HINT = """{
  "schema_version": "claim-v1",
  "image_readability": "clear | partial | unreadable",
  "candidates": [
    {
      "id": "c1",
      "quote_from_image": "图片原文",
      "normalized_claim": "完整陈述句",
      "action_type": "money_transfer | credential_request | medication_change | medical_treatment | safety_action | policy_service | purchase | public_event | general_health | none",
      "harm_type": "financial | privacy | health | safety | public | none",
      "urgency": "high | medium | none",
      "is_verifiable": true,
      "is_visual_main_subject": true,
      "visual_prominence": "dominant | prominent | peripheral | corner",
      "event_anchors": {
        "dates": ["图片中可读日期"],
        "locations": ["城市、具体地点"],
        "organizations": ["机构名称"],
        "objects": ["涉事物或事件对象"],
        "source_accounts": ["画面中的发布账号"]
      }
    }
  ],
  "visual_authenticity_question": "true | false | unknown"
}"""

SCOPE_PROMPT = """你是核验范围判断器。给定一条从图片提取的说法，判断它是否属于产品的核验范围。
支持范围：
- health 健康与保健品（偏方、疗效、营养、食品功效、保健品、用药行为）
- policy 养老政策与公共服务（补贴、通知、社保、公共服务、正式政策）
- scam 诈骗与资金风险（转账、收款、扫码、验证码、领奖、高收益、个人信息诱导）
- news 热点事件与 AI 画面（公共社会事件、灾害、公共安全、奇闻画面、疑似 AI 截图）
不支持范围（必须判 out_of_scope）：汽车、普通商品测评、企业经营、股票、娱乐八卦、影视剧情、游戏、个人观点段子、医疗诊断结论、法律结论、投资建议
规则：
1. 不确定就判 insufficient_information，不得默认归为 news
2. 画面真实性存疑且无其他可核验文字说法时，允许 domain=news
3. matched_signals 列出你判断依据的关键词"""

SCOPE_SCHEMA_HINT = """{
  "schema_version": "scope-v1",
  "claim_id": "c1",
  "scope_status": "in_scope | out_of_scope | insufficient_information",
  "domain": "health | policy | scam | news | non_factual | out_of_scope",
  "rule_id": "规则标识，如 HEALTH_MEDICATION_CHANGE",
  "matched_signals": ["关键词1", "关键词2"],
  "rejection_reason": null
}"""

EVIDENCE_PROMPT = """你是证据关系判断器。给定一条待核验说法和一份来源资料，判断资料与说法的关系。
规则：
1. 只判断语义关系，不得编造链接、机构、日期或原文
2. supporting_quote 必须逐字取自给定资料原文，不得改写
3. direct_support/direct_refute 要求主体一致且对命题本身直接表态；只谈相关话题是 related_only
4. 资料发布主体与说法主体不一致时 entity_match=false
5. 资料明显过期（被新政策废止）时 time_status=outdated
6. 资料没有提到说法中的关键数字或细节时，不得判 direct_refute——未提及不等于反驳，
   应判 related_only 或 cannot_determine；direct_refute 必须是资料对同一命题明确给出相反结论
7. 说法中的数字与资料中的数字不一致时，先确认资料原文确实在谈同一个指标再判 direct_refute
8. 待核验说法带有“事件锚点”时，资料必须至少命中同一城市/地点，并命中日期、机构或具体涉事物之一，才可判 direct_support/direct_refute；只谈同类事件一律判 related_only"""

EVIDENCE_SCHEMA_HINT = """{
  "schema_version": "evidence-v1",
  "claim_id": "c1",
  "source_id": "来源标识",
  "source_origin": "knowledge_base | designated_site | open_web",
  "claim_relation": "direct_support | direct_refute | mixed | related_only | not_related | cannot_determine",
  "entity_match": true,
  "proposition_match": true,
  "time_status": "valid | outdated | unknown",
  "supporting_quote": "资料原文片段",
  "usable_as_evidence": false,
  "rejection_codes": []
}"""


def build_evidence_prompt(
    claim: str, source_title: str, source_text: str, origin: str, source_id: str,
    event_anchors: str = "",
) -> str:
    return (
        f"{EVIDENCE_PROMPT}\n\n"
        f"待核验说法：{claim}\n"
        f"事件锚点：{event_anchors or '无'}\n"
        f"来源标识：{source_id}\n"
        f"来源层级：{origin}\n"
        f"来源标题：{source_title}\n"
        f"来源原文：\n{source_text[:3600]}"
    )


AUTHORITY_PROMPT = """你是来源权威判定器。给定一个网页的 URL、标题和正文片段，判断其发布主体的权威档位。
权威档位定义（从高到低）：
- gov_original：中国政府各级机关官网原始发布（域名 .gov.cn，或正文明确声明显示为政府部门发文）
- national_media：国家级官方媒体（新华社/人民日报/中央广播电视总台/中国新闻社/光明日报/经济日报等）
- provincial_media：省级党报党台或有明确主管单位的市场化媒体（各省日报/广电/澎湃新闻/财新/第一财经/凤凰网等）
- local_official：地市级党报党台或政府官方发布账号
- unknown：个人账号、自媒体、营销号、论坛、无法确认主体的页面

判定规则：
1. 只依据给定内容判断，不得编造发布主体
2. 正文中出现"来源：XX""据XX报道""XX电"等转载署名时，以原始发布主体定档，is_original_publisher=false
3. 正文明确为本站原创且主体可确认时 is_original_publisher=true
4. 主体无法确认或属于个人/自媒体时 source_tier=unknown, confidence=low
5. 拿不准时 confidence 降一档，宁缺毋滥"""

AUTHORITY_SCHEMA_HINT = """{
  "schema_version": "authority-v1",
  "source_tier": "gov_original | national_media | provincial_media | local_official | unknown",
  "is_authoritative": false,
  "is_original_publisher": false,
  "publisher_name": "发布主体名称（无法确认则留空）",
  "confidence": "high | medium | low",
  "rejection_reasons": []
}"""


def build_authority_prompt(url: str, title: str, page_text: str) -> str:
    return (
        f"{AUTHORITY_PROMPT}\n\n"
        f"网页 URL：{url}\n"
        f"网页标题：{title}\n"
        f"正文片段：\n{page_text[:2000]}"
    )
