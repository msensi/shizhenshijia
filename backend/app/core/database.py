"""数据库基础设施：引擎与会话。业务层禁止直接使用，走 repositories。"""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.db_models import Base


def _build_engine():
    url = get_settings().database_url
    if url.startswith("sqlite"):
        # sqlite:///relative -> 锚定到 backend/ 目录，避免 cwd 漂移。
        # Studio 会在运行时挂载 /mnt/workspace，镜像构建阶段创建的子目录可能被覆盖，
        # 因此绝对路径和相对路径都在启动时确保父目录存在。
        raw = url.split("///", 1)[1]
        db_path = Path(raw)
        if not db_path.is_absolute():
            from app.core.config import BACKEND_ROOT
            db_path = BACKEND_ROOT / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path}"
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

        # QA P1-1 修复：分析进行中再传图时 create_task 写库撞上管线进度写库，
        # SQLite 默认锁直接报 database is locked -> E-500。
        # WAL（读写不互斥）+ busy_timeout（写-写等待而非报错）双保险。
        @event.listens_for(eng, "connect")
        def _sqlite_pragma(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.close()

        return eng
    return create_engine(url)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # 轻量兼容旧版 SQLite：新增字段时保留已有测试记录
    if engine.url.get_backend_name() == "sqlite":
        columns = {c["name"] for c in inspect(engine).get_columns("analyses")}
        if "risk_alerts" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE analyses ADD COLUMN risk_alerts JSON"))


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务作用域：正常提交，异常回滚，结束关闭。"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖注入用。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
