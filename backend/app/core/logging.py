"""日志基础设施：结构化 + 脱敏。严禁输出密钥与图片原文。"""
import logging
import re

from app.core.config import get_settings

_SENSITIVE_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9]{8})[A-Za-z0-9]+"),  # dashscope key 前缀
    re.compile(r"(Bearer\s+)(\S+)", re.IGNORECASE),
]


class _DesensitizeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pat in _SENSITIVE_PATTERNS:
            msg = pat.sub(r"\1***", msg)
        record.msg = msg
        record.args = ()
        return True


def configure_logging() -> None:
    settings = get_settings()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    # 控制台
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(_DesensitizeFilter())

    handlers: list[logging.Handler] = [console]

    # 文件日志（持久化，排查 E-500 / 崩溃用）。脱敏同样生效。
    try:
        from app.core.config import BACKEND_ROOT

        log_dir = BACKEND_ROOT / "var" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.addFilter(_DesensitizeFilter())
        handlers.append(file_handler)
    except Exception:  # 文件日志失败不阻塞启动
        pass

    root = logging.getLogger()
    root.handlers.clear()
    for h in handlers:
        root.addHandler(h)
    root.setLevel(settings.log_level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
