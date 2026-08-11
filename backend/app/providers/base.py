"""Provider Adapter 抽象层（PRD 第 8 节硬性要求）。

所有模型、搜索、知识库、存储调用必须经此抽象，保证可替换。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMJsonResult:
    """一次 json_object 模式调用的结果。"""

    ok: bool
    payload: dict | None = None          # 解析后的 JSON（失败为 None）
    raw_text: str = ""                   # 模型原始文本（仅调试，禁止进用户响应）
    error: str = ""                      # 内部错误描述（进日志，不进响应）
    model: str = ""
    latency_ms: int = 0
    config_invalid: bool = False         # key 缺失/失效/欠费 -> S-503


class LLMAdapter(ABC):
    """视觉/文本模型统一接口。"""

    @abstractmethod
    async def vision_json(self, image_bytes: bytes, prompt: str, schema_hint: str) -> LLMJsonResult:
        """图片 + 提示词 -> JSON 输出（claim-v1 用）。"""

    @abstractmethod
    async def text_json(self, prompt: str, schema_hint: str) -> LLMJsonResult:
        """纯文本 -> JSON 输出（scope-v1 / evidence-v1 用）。"""


@dataclass
class KBCandidate:
    source_id: str
    title: str
    publisher: str
    url: str
    quote: str
    published_at: str | None = None
    score: float = 0.0
    qualified: bool = True
    qualification_reason: str = ""


@dataclass
class KBRetrieveResult:
    ok: bool
    candidates: list[KBCandidate] = field(default_factory=list)
    error: str = ""
    config_invalid: bool = False


class KnowledgeBaseAdapter(ABC):
    @abstractmethod
    async def retrieve(self, query: str, top_k: int) -> KBRetrieveResult:
        """语义检索 Top-K 候选。候选不能直接成为结论，须过 evidence-v1。"""

    @abstractmethod
    async def reindex(self) -> bool:
        """重建索引（管理页入口）。"""


@dataclass
class SearchResultItem:
    title: str
    url: str
    snippet: str
    summary: str = ""
    publisher: str = ""
    published_at: str | None = None


@dataclass
class SearchResult:
    ok: bool
    items: list[SearchResultItem] = field(default_factory=list)
    error: str = ""
    config_invalid: bool = False
    cost_fen: int = 0


class SearchAdapter(ABC):
    @abstractmethod
    async def search(
        self, query: str, include_domains: list[str] | None = None, count: int = 10
    ) -> SearchResult:
        """网页搜索。include_domains 用于指定权威站层（等价 site: 限定）。"""


class StorageAdapter(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> str:
        """保存文件，返回可定位路径。"""

    @abstractmethod
    def delete(self, path: str) -> None:
        """物理删除。"""

    @abstractmethod
    def exists(self, path: str) -> bool: ...
