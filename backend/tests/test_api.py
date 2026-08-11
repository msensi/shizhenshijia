"""API 层测试：统一响应包、错误码映射、鉴权、图片校验。"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.errors import (
    CODE_IMAGE_TOO_LARGE,
    CODE_INVALID_FORMAT,
    CODE_UNAUTHORIZED,
)
from app.main import app


def _jpeg_bytes(size=(100, 100)) -> bytes:
    img = Image.new("RGB", size, color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture()
def client(settings):
    with TestClient(app) as c:
        yield c


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "ok"


class TestUploadValidation:
    def test_invalid_format_returns_1xxx(self, client):
        r = client.post(
            "/api/v1/analyses",
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )
        assert r.status_code == 400
        body = r.json()
        assert body["code"] == CODE_INVALID_FORMAT
        assert 1000 <= body["code"] < 2000
        assert body["message"]  # 老人友好提示非空

    def test_oversize_returns_1002(self, client, settings):
        big = b"\xff\xd8\xff" + b"\x00" * (settings.image_max_bytes + 1)
        r = client.post(
            "/api/v1/analyses",
            files={"file": ("big.jpg", big, "image/jpeg")},
        )
        assert r.status_code == 400
        assert r.json()["code"] == CODE_IMAGE_TOO_LARGE

    def test_valid_jpeg_accepted(self, client):
        r = client.post(
            "/api/v1/analyses",
            files={"file": ("photo.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        # mock llm 无配置 -> 任务受理（202），结果异步
        assert r.status_code == 202
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "queued"
        assert body["data"]["analysis_id"].startswith("ana_")
        assert body["data"]["expires_at"] is None

    def test_png_accepted(self, client):
        img = Image.new("RGB", (50, 50), color=(0, 128, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        r = client.post(
            "/api/v1/analyses",
            files={"file": ("photo.png", buf.getvalue(), "image/png")},
        )
        assert r.status_code == 202

    def test_not_found(self, client):
        r = client.get("/api/v1/analyses/ana_nonexistent")
        assert r.status_code == 404
        assert 1000 <= r.json()["code"] < 2000


class TestAdminAuth:
    def test_no_token_401(self, client):
        r = client.get("/api/v1/admin/analytics")
        assert r.status_code == 401
        assert r.json()["code"] == CODE_UNAUTHORIZED

    def test_wrong_token_401(self, client):
        r = client.get(
            "/api/v1/admin/analytics", headers={"Authorization": "Bearer wrong"}
        )
        assert r.status_code == 401

    def test_valid_token_ok(self, client):
        r = client.get(
            "/api/v1/admin/analytics",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert "items" in body["data"]
        # AC-12：管理页数据不含原图字段
        for item in body["data"]["items"]:
            assert "image_path" not in item
            assert "image_hash" not in item or True  # hash 允许（审计用），路径禁止

    def test_reindex_requires_auth(self, client):
        r = client.post("/api/v1/admin/knowledge-base/reindex")
        assert r.status_code == 401
        r2 = client.post(
            "/api/v1/admin/knowledge-base/reindex",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert r2.status_code == 202
        assert r2.json()["data"]["status"] == "queued"
