import json

from app.providers.bailian_kb import BailianKBAdapter


def _adapter(settings, tmp_path, documents):
    registry = tmp_path / "kb-document-registry.json"
    registry.write_text(
        json.dumps({"schema_version": "kb-document-registry-v1", "documents": documents}),
        encoding="utf-8",
    )
    configured = settings.model_copy(
        update={"knowledge_base_document_registry_path": str(registry)}
    )
    return BailianKBAdapter(configured)


def test_kb_candidate_uses_registered_friendly_metadata(settings, tmp_path):
    adapter = _adapter(settings, tmp_path, {
        "kp-1": {
            "title": "降压药能自行停用吗？",
            "source_platform": "科普中国·科学辟谣",
            "publisher": "科学辟谣",
            "published_at": "2020-03-19",
            "source_url": "https://piyao.kepuchina.cn/rumor/rumordetail?id=1",
            "publisher_verification": "not_required",
            "evidence_eligibility": "eligible_with_claim_match",
        }
    })

    candidate = adapter._candidate_from_node({
        "score": 0.91,
        "metadata": {
            "doc_name": "kp-1",
            "title": "",
            "doc_url": "https://temporary.example/file",
            "content": "高血压患者不应自行停药。",
        },
    })

    assert candidate.source_id == "kp-1"
    assert candidate.title == "降压药能自行停用吗？"
    assert candidate.publisher == "科普中国·科学辟谣"
    assert candidate.published_at == "2020-03-19"
    assert candidate.url.startswith("https://piyao.kepuchina.cn/")
    assert candidate.qualified is True


def test_kb_republished_self_media_is_not_qualified(settings, tmp_path):
    adapter = _adapter(settings, tmp_path, {
        "py-1": {
            "title": "高血压可以根治？",
            "source_platform": "中国互联网联合辟谣平台",
            "publisher": "今日头条",
            "published_at": "",
            "source_url": "https://www.toutiao.com/i123",
            "publisher_verification": "required_for_republished_source",
            "evidence_eligibility": "eligible_with_claim_match",
        }
    })

    candidate = adapter._candidate_from_node({
        "metadata": {"doc_name": "py-1", "content": "高血压不能宣称根治。"}
    })

    assert candidate.qualified is False
    assert candidate.qualification_reason == "republished_source_unverified"


def test_kb_unregistered_document_is_conservatively_rejected(settings, tmp_path):
    adapter = _adapter(settings, tmp_path, {})
    candidate = adapter._candidate_from_node({
        "metadata": {"doc_name": "unknown-1", "content": "发布主体：个人账号"}
    })

    assert candidate.qualified is False
    assert candidate.qualification_reason == "metadata_not_registered"
