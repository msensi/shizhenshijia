"""JSON 契约程序校验测试（PRD 4.1-4.4 三道防线）。"""
from app.schemas.claim import ImageReadability, parse_claim_v1
from app.schemas.evidence import ClaimRelation, adjudicate_evidence, parse_evidence_v1
from app.schemas.scope import Domain, ScopeStatus, parse_scope_v1


class TestClaimV1:
    def test_valid_payload(self):
        doc = parse_claim_v1({
            "schema_version": "claim-v1",
            "image_readability": "clear",
            "candidates": [{
                "id": "c1", "quote_from_image": "血压正常后可以停药",
                "normalized_claim": "高血压患者血压正常后可以停用降压药",
                "action_type": "medication_change", "harm_type": "health",
                "urgency": "none", "is_verifiable": True,
                "is_visual_main_subject": True, "visual_prominence": "dominant",
            }],
            "visual_authenticity_question": "false",
        })
        assert doc.image_readability is ImageReadability.clear
        assert len(doc.candidates) == 1

    def test_candidates_capped_at_3(self):
        payload = {
            "image_readability": "clear",
            "candidates": [
                {"id": f"c{i}", "quote_from_image": "q", "normalized_claim": "n"}
                for i in range(5)
            ],
            "visual_authenticity_question": "false",
        }
        doc = parse_claim_v1(payload)
        assert len(doc.candidates) == 3

    def test_invalid_enum_coerced(self):
        doc = parse_claim_v1({
            "image_readability": "clear",
            "candidates": [{
                "id": "c1", "quote_from_image": "q", "normalized_claim": "n",
                "action_type": "not_a_real_type", "harm_type": "not_a_harm",
                "urgency": "super_urgent",
            }],
            "visual_authenticity_question": "maybe",
        })
        c = doc.candidates[0]
        assert c.action_type.value == "none"
        assert c.urgency.value == "none"
        assert doc.visual_authenticity_question.value == "unknown"

    def test_garbage_payload_falls_back_unreadable(self):
        doc = parse_claim_v1({"totally": "wrong"})
        assert doc.candidates == []

    def test_empty_quote_dropped(self):
        doc = parse_claim_v1({
            "image_readability": "clear",
            "candidates": [{"id": "c1", "quote_from_image": "   ", "normalized_claim": "n"}],
            "visual_authenticity_question": "false",
        })
        assert doc.candidates == []

    def test_event_anchor_details_do_not_invalidate_a_clear_claim(self):
        """公共事件常有多个涉事物；细节较多时也必须保住主核验对象。"""
        doc = parse_claim_v1({
            "image_readability": "clear",
            "candidates": [{
                "id": "c1", "quote_from_image": "北海查处锂电池黑作坊",
                "normalized_claim": "北海查处非法改装锂电池黑作坊",
                "action_type": "public_event",
                "event_anchors": {
                    "objects": ["电动车", "电动摩托车", "锂电池", "黑作坊"],
                },
            }],
        })
        assert doc.image_readability is ImageReadability.clear
        assert doc.candidates[0].event_anchors.objects[-1] == "黑作坊"


class TestScopeV1:
    def test_in_scope_health(self):
        doc = parse_scope_v1({
            "claim_id": "c1", "scope_status": "in_scope", "domain": "health",
            "rule_id": "HEALTH_MEDICATION_CHANGE", "matched_signals": ["停药"],
        })
        assert doc.scope_status is ScopeStatus.in_scope
        assert doc.domain is Domain.health

    def test_illegal_domain_forced_out_of_scope(self):
        doc = parse_scope_v1({"scope_status": "in_scope", "domain": "crypto_trading"})
        assert doc.domain is Domain.out_of_scope

    def test_illegal_status_defaults_insufficient(self):
        doc = parse_scope_v1({"scope_status": "whatever"})
        assert doc.scope_status is ScopeStatus.insufficient_information

    def test_garbage_defaults_not_in_scope(self):
        doc = parse_scope_v1({})
        assert doc.scope_status is not ScopeStatus.in_scope


class TestEvidenceV1:
    def test_adjudication_all_conditions(self):
        ev = parse_evidence_v1({
            "claim_relation": "direct_refute", "entity_match": True,
            "proposition_match": True, "time_status": "valid",
            "supporting_quote": "不应自行停用降压药",
        })
        ev = adjudicate_evidence(ev, source_is_qualified=True)
        assert ev.usable_as_evidence is True

    def test_unqualified_source_rejected(self):
        ev = parse_evidence_v1({
            "claim_relation": "direct_support", "entity_match": True,
            "time_status": "valid", "supporting_quote": "q",
        })
        ev = adjudicate_evidence(ev, source_is_qualified=False)
        assert ev.usable_as_evidence is False
        assert "UNQUALIFIED_SOURCE" in ev.rejection_codes

    def test_related_only_rejected(self):
        ev = parse_evidence_v1({
            "claim_relation": "related_only", "entity_match": True,
            "time_status": "valid", "supporting_quote": "q",
        })
        ev = adjudicate_evidence(ev, source_is_qualified=True)
        assert ev.usable_as_evidence is False

    def test_proposition_mismatch_rejected(self):
        ev = parse_evidence_v1({
            "claim_relation": "direct_support", "entity_match": True,
            "proposition_match": False, "time_status": "valid",
            "supporting_quote": "同一主体发布了另一条相关消息",
        })
        ev = adjudicate_evidence(ev, source_is_qualified=True)
        assert ev.usable_as_evidence is False
        assert "PROPOSITION_MISMATCH" in ev.rejection_codes

    def test_outdated_rejected(self):
        ev = parse_evidence_v1({
            "claim_relation": "direct_support", "entity_match": True,
            "time_status": "outdated", "supporting_quote": "q",
        })
        ev = adjudicate_evidence(ev, source_is_qualified=True)
        assert ev.usable_as_evidence is False
        assert "OUTDATED" in ev.rejection_codes

    def test_illegal_relation_coerced(self):
        ev = parse_evidence_v1({"claim_relation": "strongly_agrees"})
        assert ev.claim_relation is ClaimRelation.cannot_determine
