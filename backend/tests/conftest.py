import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# 测试环境：隔离数据库与存储目录，mock providers
os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = "sqlite:///var/test_szsj.db"
os.environ["STORAGE_LOCAL_DIR"] = "var/test_images"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["KNOWLEDGE_BASE_PROVIDER"] = "mock"
os.environ["SEARCH_PROVIDER"] = "mock"
os.environ["ADMIN_ACCESS_TOKEN"] = "test-admin-token"
# 既有集成测试逐层验证传统流程；快速路径由专门测试覆盖。
os.environ["FAST_SCOPE_ENABLED"] = "false"
os.environ["PARALLEL_EVIDENCE_ENABLED"] = "false"

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.db_models import Base  # noqa: E402


@pytest.fixture()
def settings():
    get_settings.cache_clear()
    s = get_settings()
    yield s
    get_settings.cache_clear()


@pytest.fixture()
def session(settings, tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TestingSession() as s:
        yield s
