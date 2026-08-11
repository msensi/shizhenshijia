"""Provider 装配：按配置选择实现。唯一装配点，业务层只依赖抽象。"""
from app.core.config import Settings
from app.providers.bailian_kb import BailianKBAdapter, MockKBAdapter
from app.providers.bailian_search import BailianSearchAdapter, MockSearchAdapter
from app.providers.base import (
    KnowledgeBaseAdapter,
    LLMAdapter,
    SearchAdapter,
    StorageAdapter,
)
from app.providers.dashscope_llm import DashScopeLLMAdapter, MockLLMAdapter
from app.providers.local_storage import LocalStorageAdapter
from app.providers.qwen_web_search import QwenWebSearchAdapter


def build_llm(settings: Settings) -> LLMAdapter:
    if settings.llm_provider == "dashscope":
        return DashScopeLLMAdapter(settings)
    if settings.llm_provider == "mock":
        return MockLLMAdapter()
    raise ValueError(f"unknown llm provider: {settings.llm_provider}")


def build_kb(settings: Settings) -> KnowledgeBaseAdapter:
    if settings.knowledge_base_provider == "bailian":
        return BailianKBAdapter(settings)
    return MockKBAdapter()


def build_search(settings: Settings) -> SearchAdapter:
    if settings.search_provider == "qwen":
        return QwenWebSearchAdapter(settings)
    if settings.search_provider == "bailian":
        return BailianSearchAdapter(settings)
    if settings.search_provider == "mock":
        return MockSearchAdapter()
    raise ValueError(f"unknown search provider: {settings.search_provider}")


def build_storage(settings: Settings) -> StorageAdapter:
    if settings.storage_provider == "local":
        return LocalStorageAdapter(settings)
    raise ValueError(f"unknown storage provider: {settings.storage_provider}")
