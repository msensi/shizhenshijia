"""图片处理测试：格式校验、大小上限、HEIF 转换、哈希。"""
import io

import pytest
from PIL import Image

from app.core.errors import AppError
from app.services import image_service


def _img_bytes(fmt: str, size=(80, 80)) -> bytes:
    img = Image.new("RGB", size, color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


class TestValidate:
    def test_jpeg_passthrough_normalized(self, settings):
        out = image_service.validate_and_normalize(_img_bytes("JPEG"), "a.jpg", settings)
        assert out[:3] == b"\xff\xd8\xff"  # JPEG 魔数

    def test_png_converted_to_jpeg(self, settings):
        out = image_service.validate_and_normalize(_img_bytes("PNG"), "a.png", settings)
        assert out[:3] == b"\xff\xd8\xff"

    def test_bad_format_rejected(self, settings):
        with pytest.raises(AppError) as exc:
            image_service.validate_and_normalize(b"plain text", "a.txt", settings)
        assert exc.value.code == 1001

    def test_oversize_rejected(self, settings):
        big = b"\xff\xd8\xff" + b"\x00" * (settings.image_max_bytes + 1)
        with pytest.raises(AppError) as exc:
            image_service.validate_and_normalize(big, "a.jpg", settings)
        assert exc.value.code == 1002

    def test_corrupted_rejected(self, settings):
        with pytest.raises(AppError) as exc:
            image_service.validate_and_normalize(b"\xff\xd8\xffbroken", "a.jpg", settings)
        assert exc.value.code == 1003

    def test_heif_supported_when_lib_present(self, settings):
        pytest.importorskip("pillow_heif")
        from pillow_heif import register_heif_opener
        register_heif_opener()
        img = Image.new("RGB", (60, 60), color=(10, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="HEIF")
        out = image_service.validate_and_normalize(buf.getvalue(), "a.heic", settings)
        assert out[:3] == b"\xff\xd8\xff"  # 已转 JPEG

    def test_empty_rejected(self, settings):
        with pytest.raises(AppError):
            image_service.validate_and_normalize(b"", "a.jpg", settings)


class TestHash:
    def test_hash_stable(self):
        data = b"hello"
        assert image_service.sha256_hex(data) == image_service.sha256_hex(data)
        assert len(image_service.sha256_hex(data)) == 64
