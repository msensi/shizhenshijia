import pytest

from app.services.page_fetcher import _decode_html, _is_public_url


def test_html_meta_charset_overrides_default_utf8():
    body = '<meta charset="gb2312">城乡居民基础养老金提高20元'.encode("gb18030")
    assert "养老金提高20元" in _decode_html(body, "utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1:8000/",
        "http://10.0.0.8/internal",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
    ],
)
async def test_private_and_non_http_targets_are_blocked(url):
    assert await _is_public_url(url) is False


@pytest.mark.asyncio
async def test_public_literal_is_allowed():
    assert await _is_public_url("https://8.8.8.8/") is True
