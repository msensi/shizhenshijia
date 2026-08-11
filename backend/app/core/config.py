"""配置加载：.env -> Settings。所有配置项唯一来源，禁止业务文件硬编码。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 模型服务
    llm_provider: str = "dashscope"
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    vision_model: str = "qwen3-vl-flash-2026-01-22"
    text_model: str = "qwen-plus"
    search_model: str = ""
    llm_temperature: float = 0.0
    vision_model_fallback: str = "qwen3-vl-plus-2025-12-19"
    text_model_fallback: str = "qwen-flash"

    # 知识库
    knowledge_base_provider: str = "mock"
    knowledge_base_url: str = ""
    knowledge_base_api_key: str = ""
    knowledge_base_collection: str = "szsj_authority_evidence"
    knowledge_base_agent_id: str = ""  # 百炼知识检索服务(agent)实例 ID，发布后获取
    knowledge_base_top_k: int = 5
    knowledge_base_document_registry_path: str = "config/kb_document_registry.json"
    embedding_model: str = "text-embedding-v4"

    # 搜索与预算（千问内置联网搜索；key 复用 llm_api_key）
    search_provider: str = "qwen"
    search_api_key: str = ""
    search_base_url: str = "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp"
    integrated_search_base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    integrated_search_model: str = "qwen-plus"
    integrated_search_timeout_seconds: float = 20.0
    search_max_calls_per_analysis: int = 3
    search_daily_quota: int = 600
    search_daily_cost_limit_fen: int = 2500
    source_registry_path: str = "config/source_registry.yaml"
    search_routes_path: str = "config/search_routes.yaml"
    # 百炼联网搜索单次调用成本（分）
    search_cost_per_call_fen: int = 4

    # 快速核验：明确场景由程序归类；三层证据源并行查找，疑难情况继续深查。
    fast_scope_enabled: bool = True
    parallel_evidence_enabled: bool = True
    fast_evidence_judge_limit: int = 2

    # 排序规则
    visual_demotion_score: int = 18

    # MCP（MVP 关闭）
    mcp_enabled: bool = False
    mcp_search_server_url: str = ""
    mcp_search_auth_token: str = ""
    mcp_knowledge_server_url: str = ""
    mcp_knowledge_auth_token: str = ""

    # 存储与隐私
    storage_provider: str = "local"
    storage_local_dir: str = "var/images"
    storage_bucket: str = ""
    storage_region: str = ""
    storage_access_key_id: str = ""
    storage_access_key_secret: str = ""
    image_retention_days: int = 0
    # 兼容旧部署变量；当前产品隐私规则强制不落盘，业务代码不会读取此值。
    keep_original_image: bool = False
    admin_access_token: str = ""

    # 图片校验
    allowed_image_formats: str = "jpg,jpeg,png,heif,heic"
    heif_convert_to: str = "jpeg"
    image_max_size_mb: int = 10
    analysis_timeout_seconds: int = 60

    # 服务运行
    app_env: str = "development"
    database_url: str = "sqlite:///var/szsj.db"
    log_level: str = "INFO"

    @property
    def allowed_formats(self) -> set[str]:
        return {f.strip().lower() for f in self.allowed_image_formats.split(",") if f.strip()}

    @property
    def image_max_bytes(self) -> int:
        return self.image_max_size_mb * 1024 * 1024

    @property
    def storage_dir(self) -> Path:
        p = Path(self.storage_local_dir)
        return p if p.is_absolute() else BACKEND_ROOT / p

    @property
    def source_registry_file(self) -> Path:
        p = Path(self.source_registry_path)
        return p if p.is_absolute() else BACKEND_ROOT / p

    @property
    def search_routes_file(self) -> Path:
        p = Path(self.search_routes_path)
        return p if p.is_absolute() else BACKEND_ROOT / p

    @property
    def knowledge_base_document_registry_file(self) -> Path:
        p = Path(self.knowledge_base_document_registry_path)
        return p if p.is_absolute() else BACKEND_ROOT / p


@lru_cache
def get_settings() -> Settings:
    return Settings()
