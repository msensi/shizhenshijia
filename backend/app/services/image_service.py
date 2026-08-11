"""图片校验与处理：格式/大小校验、HEIF->JPEG 转换、哈希计算。

AC-01：JPG/JPEG/PNG/HEIF <=10MB 必须接受；不合规返回 1xxx + 老人友好提示。
"""
import hashlib
import io

from PIL import Image

from app.core.config import Settings
from app.core.errors import (
    CODE_IMAGE_TOO_LARGE,
    CODE_IMAGE_UNREADABLE,
    CODE_INVALID_FORMAT,
    AppError,
)

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIF_AVAILABLE = True
except ImportError:  # pragma: no cover - 环境缺依赖时 HEIF 按不支持处理
    _HEIF_AVAILABLE = False


def sniff_extension(filename: str | None, content: bytes) -> str:
    """按文件名后缀与魔数推断格式，白名单外直接拒绝。"""
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[1].lower()
    if not ext:
        if content[:3] == b"\xff\xd8\xff":
            ext = "jpg"
        elif content[:8] == b"\x89PNG\r\n\x1a\n":
            ext = "png"
        elif content[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypmsf1"):
            ext = "heic"
    return ext


def validate_and_normalize(content: bytes, filename: str | None, settings: Settings) -> bytes:
    """校验 + 归一化为 JPEG bytes（供视觉模型与存储）。不合规抛 AppError(1xxx)。"""
    if not content:
        raise AppError(CODE_IMAGE_UNREADABLE, "图片没有读到内容，您重新上传一次试试")

    ext = sniff_extension(filename, content)
    if ext not in settings.allowed_formats:
        raise AppError(
            CODE_INVALID_FORMAT,
            "这个图片格式暂时不支持，您换成 JPG 或 PNG 格式的图片再试",
        )
    if len(content) > settings.image_max_bytes:
        raise AppError(
            CODE_IMAGE_TOO_LARGE,
            f"图片太大了，您换成 {settings.image_max_size_mb}MB 以内的图片再试",
        )

    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        raise AppError(
            CODE_IMAGE_UNREADABLE, "这张图片好像损坏打不开了，您换一张再试"
        ) from None

    # HEIF/HEIC 及其他格式统一转 JPEG 送视觉模型（AC-01）
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
