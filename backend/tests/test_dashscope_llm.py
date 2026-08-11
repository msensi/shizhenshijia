"""DashScope Adapter 的轻量程序逻辑测试。"""

from app.providers.dashscope_llm import _vision_has_no_usable_claim


def test_vision_empty_claim_triggers_fallback_review():
    assert _vision_has_no_usable_claim({"image_readability": "unreadable", "candidates": []})
    assert _vision_has_no_usable_claim({"image_readability": "clear", "candidates": []})
    assert not _vision_has_no_usable_claim({
        "image_readability": "clear", "candidates": [{"id": "c1"}],
    })
