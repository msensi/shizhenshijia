"""DashScope LLM Adapter（OpenAI 兼容端点，json_object 模式）。

纪律（ADR-001）：非思考模式、temperature=0、必带快照版本号、禁 -latest。
已知坑（SPEC 11）：json_object 只保合法 JSON 不保字段级 Schema -> Pydantic 兜底。
"""
import base64
import json
import re
import time

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.base import LLMAdapter, LLMJsonResult

logger = get_logger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    """从模型输出提取 JSON：优先整体解析，退化到首个大括号块。"""
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    m = _JSON_BLOCK.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _vision_has_no_usable_claim(payload: dict | None) -> bool:
    """视觉模型偶尔会把清楚的长图误判为看不清；仅此时启用备用模型复核。"""
    if not isinstance(payload, dict):
        return True
    return payload.get("image_readability") == "unreadable" or not payload.get("candidates")


class DashScopeLLMAdapter(LLMAdapter):
    def __init__(self, settings: Settings, timeout: float = 45.0) -> None:
        self._s = settings
        self._timeout = timeout

    def _config_invalid_result(self, model: str) -> LLMJsonResult:
        return LLMJsonResult(
            ok=False, error="llm api key not configured", model=model, config_invalid=True
        )

    async def _chat(self, model: str, messages: list[dict]) -> LLMJsonResult:
        if not self._s.llm_api_key:
            return self._config_invalid_result(model)
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._s.llm_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self._s.llm_api_key}"},
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": self._s.llm_temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
        except httpx.TimeoutException:
            return LLMJsonResult(ok=False, error="llm request timeout", model=model)
        except httpx.HTTPError as exc:
            logger.warning("llm request failed model=%s err=%s", model, type(exc).__name__)
            return LLMJsonResult(ok=False, error="llm request failed", model=model)

        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code in (401, 403):
            return LLMJsonResult(
                ok=False, error="llm auth failed", model=model,
                latency_ms=latency_ms, config_invalid=True,
            )
        if resp.status_code == 402:
            return LLMJsonResult(
                ok=False, error="llm arrears", model=model,
                latency_ms=latency_ms, config_invalid=True,
            )
        if resp.status_code != 200:
            return LLMJsonResult(
                ok=False, error=f"llm http {resp.status_code}",
                model=model, latency_ms=latency_ms,
            )
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, json.JSONDecodeError):
            return LLMJsonResult(
                ok=False, error="llm malformed response", model=model, latency_ms=latency_ms
            )
        payload = _extract_json(content) if isinstance(content, str) else None
        if payload is None:
            return LLMJsonResult(
                ok=False, raw_text=content if isinstance(content, str) else "",
                error="llm non-json output", model=model, latency_ms=latency_ms,
            )
        return LLMJsonResult(
            ok=True, payload=payload, raw_text=content, model=model, latency_ms=latency_ms
        )

    async def vision_json(self, image_bytes: bytes, prompt: str, schema_hint: str) -> LLMJsonResult:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": f"{prompt}\n\n只输出 JSON，字段结构：\n{schema_hint}"},
                ],
            }
        ]
        result = await self._chat(self._s.vision_model, messages)
        # 降级重试（ADR-001）：主视觉模型网络抖动/超时/5xx 时，用备用快照重试一次。
        # 配置错误（config_invalid：欠费/key 失效）不重试，直接上抛 S-503。
        if not result.ok and not result.config_invalid and self._s.vision_model_fallback:
            logger.warning(
                "vision primary failed model=%s err=%s -> fallback %s",
                self._s.vision_model, result.error, self._s.vision_model_fallback,
            )
            retry = await self._chat(self._s.vision_model_fallback, messages)
            if retry.ok:
                return retry
            # 备用也失败，返回主模型的错误（更贴近真实根因）
        # 清楚截图被误判为“看不清”会直接结束核验。仅在未提取到任何候选时，
        # 用备用视觉模型复核一次；正常识图没有额外延迟或费用。
        if result.ok and self._s.vision_model_fallback and _vision_has_no_usable_claim(result.payload):
            logger.warning(
                "vision returned no usable claim model=%s -> fallback %s",
                self._s.vision_model, self._s.vision_model_fallback,
            )
            retry = await self._chat(self._s.vision_model_fallback, messages)
            if retry.ok and not _vision_has_no_usable_claim(retry.payload):
                return retry
        return result

    async def text_json(self, prompt: str, schema_hint: str) -> LLMJsonResult:
        messages = [
            {"role": "user", "content": f"{prompt}\n\n只输出 JSON，字段结构：\n{schema_hint}"}
        ]
        result = await self._chat(self._s.text_model, messages)
        # 降级重试：主文本模型抖动时用备用快照（qwen-flash）重试一次
        if not result.ok and not result.config_invalid and self._s.text_model_fallback:
            logger.warning(
                "text primary failed model=%s err=%s -> fallback %s",
                self._s.text_model, result.error, self._s.text_model_fallback,
            )
            retry = await self._chat(self._s.text_model_fallback, messages)
            if retry.ok:
                return retry
        return result


class MockLLMAdapter(LLMAdapter):
    """假数据 Adapter：key 未配置或测试环境跑通全链路用。

    通过 queue_* 方法预置响应；未预置时返回配置缺失。
    """

    def __init__(self) -> None:
        self._vision_queue: list[LLMJsonResult] = []
        self._text_queue: list[LLMJsonResult] = []

    def queue_vision(self, payload: dict | None, **kwargs) -> None:
        self._vision_queue.append(
            LLMJsonResult(ok=payload is not None, payload=payload, **kwargs)
        )

    def queue_text(self, payload: dict | None, **kwargs) -> None:
        self._text_queue.append(
            LLMJsonResult(ok=payload is not None, payload=payload, **kwargs)
        )

    async def vision_json(self, image_bytes: bytes, prompt: str, schema_hint: str) -> LLMJsonResult:
        if self._vision_queue:
            return self._vision_queue.pop(0)
        return LLMJsonResult(ok=False, error="mock vision not queued", config_invalid=True)

    async def text_json(self, prompt: str, schema_hint: str) -> LLMJsonResult:
        if self._text_queue:
            return self._text_queue.pop(0)
        return LLMJsonResult(ok=False, error="mock text not queued", config_invalid=True)
