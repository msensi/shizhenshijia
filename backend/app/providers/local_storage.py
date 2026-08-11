"""本地磁盘 Storage Adapter（留 OSS 切换口）。"""
from pathlib import Path

from app.core.config import Settings
from app.providers.base import StorageAdapter


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, settings: Settings) -> None:
        self._root = settings.storage_dir
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> str:
        # key 只允许安全文件名，防路径穿越
        safe = Path(key).name
        path = self._root / safe
        path.write_bytes(data)
        return str(path)

    def delete(self, path: str) -> None:
        p = Path(path)
        try:
            if p.exists() and p.is_file():
                p.unlink()
        except OSError:
            pass

    def exists(self, path: str) -> bool:
        return Path(path).is_file()
