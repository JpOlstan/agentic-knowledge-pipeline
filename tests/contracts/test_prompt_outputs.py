from knowledge_agents.domain.contracts import (
    AcquisitionPacket,
    DraftPackage,
    ReviewPackage,
)

RUN_ID = "run-0123456789abcdef"
HASH_A = "a" * 64
HASH_B = "b" * 64
CREATED_AT = "2026-07-21T00:00:00Z"


def source_payload() -> dict[str, object]:
    return {
        "source_id": "source-1",
        "source_type": "web_article",
        "acquisition_method": "static_html",
        "canonical_ref": "https://example.com/article",
        "title": "Example article",
        "publisher": "Example Publisher",
        "retrieved_at": CREATED_AT,
        "content_hash": HASH_A,
        "created_at": CREATED_AT,
    }


def test_agent_1_output_fixture_validates_against_production_contract() -> None:
    packet = AcquisitionPacket.model_validate(
        {
            "run_id": RUN_ID,
            "source": source_payload(),
            "claims": [
                {
                    "claim_id": "claim-1",
                    "text": "Memory is distinct from transient state.",
                    "classification": "durable",
                    "evidence_ids": ["evidence-1"],
                    "supported": True,
                }
            ],
            "concepts": [
                {
                    "concept_id": "concept-1",
                    "name": "Agent memory",
                    "summary": "Durable information available across interactions.",
                    "classification": "durable",
                    "evidence_ids": ["evidence-1"],
                }
            ],
            "evidence_map": {"claim-1": ["evidence-1"]},
            "coverage_report": {
                "covered_topics": ["memory"],
                "missing_topics": [],
                "completeness": 1,
            },
            "warnings": [],
            "created_at": CREATED_AT,
        }
    )

    assert packet.claims[0].supported
    assert packet.schema_version == "1"


def test_agent_2_output_fixture_supports_multiple_atomic_drafts() -> None:
    package = DraftPackage.model_validate(
        {
            "run_id": RUN_ID,
            "drafts": [
                {
                    "note_id": "agent-memory",
                    "title": "Agent memory",
                    "body_sections": {"Summary": "Memory persists beyond transient state."},
                    "source_claim_ids": ["claim-1"],
                    "proposed_action": "create",
                    "content_hash": HASH_A,
                },
                {
                    "note_id": "memory-consolidation",
                    "title": "Memory consolidation",
                    "body_sections": {"Summary": "Consolidation organizes retained information."},
                    "source_claim_ids": ["claim-2"],
                    "proposed_action": "create",
                    "content_hash": HASH_B,
                },
            ],
            "curation_decisions": [
                {
                    "note_id": "agent-memory",
                    "action": "create",
                    "rationale": "No promoted note covers the concept.",
                },
                {
                    "note_id": "memory-consolidation",
                    "action": "create",
                    "rationale": "The concept is independently reusable.",
                },
            ],
            "retrieval_refs": [],
            "package_hash": HASH_A,
            "created_at": CREATED_AT,
        }
    )

    assert len(package.drafts) == 2


def test_agent_3_output_fixture_links_decisions_to_exact_hashes() -> None:
    package = ReviewPackage.model_validate(
        {
            "run_id": RUN_ID,
            "reviews": [
                {
                    "note_id": "agent-memory",
                    "reviewed_hash": HASH_A,
                    "status": "ready",
                    "issues": [],
                    "required_changes": [],
                    "promotion_eligible": True,
                },
                {
                    "note_id": "memory-consolidation",
                    "reviewed_hash": HASH_B,
                    "status": "enrichment_required",
                    "issues": ["Evidence is incomplete."],
                    "required_changes": ["Add primary support."],
                    "promotion_eligible": False,
                },
            ],
            "blocked_note_ids": ["memory-consolidation"],
            "approved_note_hashes": {"agent-memory": HASH_A},
            "terminal_recommendation": "partially_ready",
            "created_at": CREATED_AT,
        }
    )

    assert package.approved_note_hashes["agent-memory"] == HASH_A
    assert package.blocked_note_ids == ("memory-consolidation",)
