"""百炼 RAG 知识库 Adapter + Mock 实现。

用户参数（workspace/index/API 形态）到位前用 Mock；到位后填 .env
并设 KNOWLEDGE_BASE_PROVIDER=bailian 即切换，接口不变。
"""
import json
import re

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.base import KBCandidate, KBRetrieveResult, KnowledgeBaseAdapter
from app.services.source_registry import get_source_registry

logger = get_logger(__name__)

# 从辟谣正文尾部解析来源元信息（科普中国/科学辟谣等平台抓取格式）
_PUBLISHER_RE = re.compile(r"发布主体[：:]\s*([^\n\r]+)")
_DATE_RE = re.compile(r"发布日期[：:]\s*([0-9]{4}[-年][0-9]{1,2}[-月][0-9]{1,2})")


def _parse_source_meta(content: str) -> tuple[str, str | None]:
    """从 content 文本提取发布主体与发布日期；缺失返回空串/None。"""
    publisher = ""
    published_at: str | None = None
    m = _PUBLISHER_RE.search(content)
    if m:
        publisher = m.group(1).strip()
    d = _DATE_RE.search(content)
    if d:
        published_at = d.group(1).replace("年", "-").replace("月", "-").replace("日", "")
    return publisher, published_at


class BailianKBAdapter(KnowledgeBaseAdapter):
    """百炼 RAG 知识检索适配（知识检索 Search 接口）。

    接口形态（实测对齐，help.aliyun.com/zh/model-studio/knowledgesearch）：
    - 请求：POST {knowledge_base_url}，body 仅 agent_id + query（images 可选）
      检索策略（多库权重/混排）已在控制台预配置进 agent_config，请求中不暴露。
    - 响应：data.nodes[]，每个 node = {score, metadata:{doc_url,title,content,...}, text}
    - 发布主体/日期在 content 文本内（如"来源平台：科普中国·科学辟谣\\n发布主体：X\\n发布日期：Y"）
    """

    def __init__(self, settings: Settings, timeout: float = 15.0) -> None:
        self._s = settings
        self._timeout = timeout
        self._document_registry = self._load_document_registry()

    def _load_document_registry(self) -> dict[str, dict[str, str]]:
        path = self._s.knowledge_base_document_registry_file
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            documents = payload.get("documents") or {}
            if not isinstance(documents, dict):
                raise ValueError("documents must be an object")
            logger.info("kb document registry loaded documents=%d", len(documents))
            return documents
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
            logger.error("kb document registry unavailable err=%s", type(exc).__name__)
            return {}

    @staticmethod
    def _document_id(meta: dict) -> str:
        # 百炼实测主要在 doc_name 返回导入时的 document_id。
        # _id 是百炼内部 file_xxx 标识，不能用于匹配导入清单。
        return str(meta.get("doc_name") or meta.get("doc_id") or meta.get("_id") or "")

    def _source_policy(self, record: dict[str, str] | None) -> tuple[bool, str]:
        """执行清洗阶段已经确定的证据来源规则。"""
        if not record:
            return False, "metadata_not_registered"
        eligibility = record.get("evidence_eligibility", "")
        if not eligibility.startswith("eligible"):
            return False, "evidence_not_eligible"
        verification = record.get("publisher_verification", "")
        if verification != "required_for_republished_source":
            return True, "verified_platform"

        publisher = record.get("publisher", "").strip()
        source_platform = record.get("source_platform", "").strip()
        if publisher and publisher == source_platform:
            return True, "platform_original"
        if publisher and get_source_registry().tier_for_publisher(publisher):
            return True, "authoritative_republisher"
        return False, "republished_source_unverified"

    def _candidate_from_node(self, node: dict) -> KBCandidate:
        meta = node.get("metadata") or {}
        content = str(meta.get("content") or node.get("text") or "")
        document_id = self._document_id(meta)
        record = self._document_registry.get(document_id)
        fallback_publisher, fallback_published_at = _parse_source_meta(content)
        qualified, qualification_reason = self._source_policy(record)
        title = str(
            (record or {}).get("title")
            or meta.get("title")
            or meta.get("doc_name")
            or ""
        )
        publisher = str((record or {}).get("source_platform") or fallback_publisher)
        published_at = str(
            (record or {}).get("published_at") or fallback_published_at or ""
        ) or None
        url = str(
            (record or {}).get("source_url")
            or meta.get("doc_url")
            or meta.get("_original_file_url")
            or ""
        )
        return KBCandidate(
            source_id=document_id,
            title=title,
            publisher=publisher,
            url=url,
            quote=content,
            published_at=published_at,
            score=float(node.get("score") or meta.get("_score") or 0.0),
            qualified=qualified,
            qualification_reason=qualification_reason,
        )

    async def retrieve(self, query: str, top_k: int) -> KBRetrieveResult:
        if (
            not self._s.knowledge_base_url
            or not self._s.knowledge_base_api_key
            or not self._s.knowledge_base_agent_id
        ):
            return KBRetrieveResult(
                ok=False, error="knowledge base not configured", config_invalid=True
            )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._s.knowledge_base_url,
                    headers={
                        "Authorization": f"Bearer {self._s.knowledge_base_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "agent_id": self._s.knowledge_base_agent_id,
                        "query": query,
                    },
                )
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.warning("kb retrieve failed err=%s", type(exc).__name__)
            return KBRetrieveResult(ok=False, error="kb request failed")
        if resp.status_code in (401, 403):
            return KBRetrieveResult(ok=False, error="kb auth failed", config_invalid=True)
        if resp.status_code != 200:
            return KBRetrieveResult(ok=False, error=f"kb http {resp.status_code}")

        try:
            body = resp.json()
        except Exception:
            return KBRetrieveResult(ok=False, error="kb malformed response")
        # 百炼业务层错误码：code != Success 视为失败
        if body.get("code") not in ("Success", "success", None):
            msg = body.get("message") or body.get("code") or "kb business error"
            return KBRetrieveResult(ok=False, error=f"kb error: {msg}")

        nodes = (body.get("data") or {}).get("nodes") or []
        candidates = [self._candidate_from_node(node) for node in nodes[: max(top_k, 1)]]
        return KBRetrieveResult(ok=True, candidates=candidates)

    async def reindex(self) -> bool:
        # 百炼侧索引由用户在其控制台维护；本端仅受理任务并记录审计
        logger.info("kb reindex requested (bailian managed externally)")
        return True


class MockKBAdapter(KnowledgeBaseAdapter):
    """Mock 知识库：预置候选队列，默认返回空命中（走指定站/开放搜索路径）。"""

    def __init__(self) -> None:
        self._queue: list[KBRetrieveResult] = []

    def queue(self, result: KBRetrieveResult) -> None:
        self._queue.append(result)

    async def retrieve(self, query: str, top_k: int) -> KBRetrieveResult:
        if self._queue:
            return self._queue.pop(0)
        return KBRetrieveResult(ok=True, candidates=[])

    async def reindex(self) -> bool:
        return True
