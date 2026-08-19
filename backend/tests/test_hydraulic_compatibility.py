"""Contract tests for public/hydraulic topology identity rewriting."""

import pytest

from app.hydraulic.compatibility import (
    HydraulicCompatibilityMapping,
    HydraulicCompatibilityMappingError,
    rewrite_legacy_topology_references,
)


def test_rewrite_uses_authoritative_ids_when_public_sequences_are_different() -> None:
    """Every solver-facing reference must leave the public ID domain explicitly."""

    mapping = HydraulicCompatibilityMapping(
        legacy_node_to_hydraulic_node={1001: 11, 1002: 12},
        legacy_segment_to_hydraulic_branch={2001: 21},
        legacy_cross_section_to_hydraulic_cross_section={3001: 31},
    )
    payload = {
        "boundary_conditions": [
            {"id": 1, "target_node_id": 1001},
            {"id": 2, "target_node_id": None},
        ],
        "gates": [{
            "id": 3,
            "upstream_node_id": 1001,
            "downstream_node_id": 1002,
            "river_segment_id": 2001,
        }],
        "pumps": [{
            "id": 4,
            "intake_node_id": 1002,
            "outlet_node_id": 1001,
        }],
        "dispatch_plan": {
            "rules": [
                {
                    "id": 5,
                    "observation_type": "node_water_level",
                    "observation_object_id": 1001,
                },
                {
                    "id": 6,
                    "observation_type": "section_water_level",
                    "observation_object_id": 3001,
                },
                {
                    "id": 7,
                    "observation_type": "gate_head_difference",
                    "observation_object_id": 4001,
                },
                {
                    "id": 8,
                    "observation_type": "elapsed_time",
                    "observation_object_id": None,
                },
            ],
        },
    }

    rewritten = rewrite_legacy_topology_references(payload, mapping)

    assert 1001 != 11 and 1002 != 12 and 2001 != 21
    assert [item["target_node_id"] for item in rewritten["boundary_conditions"]] == [
        11, None,
    ]
    assert rewritten["gates"][0] == {
        "id": 3,
        "upstream_node_id": 11,
        "downstream_node_id": 12,
        "river_segment_id": 21,
    }
    assert rewritten["pumps"][0]["intake_node_id"] == 12
    assert rewritten["pumps"][0]["outlet_node_id"] == 11
    assert [
        rule["observation_object_id"]
        for rule in rewritten["dispatch_plan"]["rules"]
    ] == [11, 31, 4001, None]
    assert payload["boundary_conditions"][0]["target_node_id"] == 1001
    assert payload["dispatch_plan"]["rules"][0]["observation_object_id"] == 1001
    assert mapping.as_payload()["river_nodes"][0] == {
        "legacy_river_node_id": 1001,
        "hydraulic_node_id": 11,
    }
    assert mapping.as_payload()["cross_sections"][0] == {
        "legacy_cross_section_id": 3001,
        "hydraulic_cross_section_id": 31,
    }


@pytest.mark.parametrize(
    ("collection_name", "field_name", "legacy_id"),
    [
        ("boundary_conditions", "target_node_id", 9991),
        ("gates", "upstream_node_id", 9992),
        ("gates", "downstream_node_id", 9993),
        ("gates", "river_segment_id", 9994),
        ("pumps", "intake_node_id", 9995),
        ("pumps", "outlet_node_id", 9996),
    ],
)
def test_rewrite_fails_closed_for_every_unmapped_reference(
    collection_name: str, field_name: str, legacy_id: int
) -> None:
    """An unresolved non-null reference is a readiness error, never a skipped asset."""

    mapping = HydraulicCompatibilityMapping(
        legacy_node_to_hydraulic_node={1001: 11},
        legacy_segment_to_hydraulic_branch={2001: 21},
        legacy_cross_section_to_hydraulic_cross_section={3001: 31},
    )
    payload = {collection_name: [{"id": 7, field_name: legacy_id}]}

    with pytest.raises(
        HydraulicCompatibilityMappingError,
        match=rf"{field_name}.*{legacy_id}.*without a verified",
    ):
        rewrite_legacy_topology_references(payload, mapping)


@pytest.mark.parametrize(
    ("observation_type", "legacy_id", "expected_table"),
    [
        ("node_water_level", 9991, "river_node"),
        ("section_water_level", 9992, "cross_section"),
    ],
)
def test_dispatch_rule_rewrite_fails_closed_for_unmapped_legacy_id(
    observation_type: str, legacy_id: int, expected_table: str
) -> None:
    """A rule may never retain an unresolved public node or section identifier."""

    mapping = HydraulicCompatibilityMapping(
        legacy_node_to_hydraulic_node={1001: 11},
        legacy_segment_to_hydraulic_branch={2001: 21},
        legacy_cross_section_to_hydraulic_cross_section={3001: 31},
    )
    payload = {
        "dispatch_plan": {
            "rules": [{
                "id": 9,
                "observation_type": observation_type,
                "observation_object_id": legacy_id,
            }]
        }
    }

    with pytest.raises(
        HydraulicCompatibilityMappingError,
        match=rf"observation_object_id.*{expected_table} {legacy_id}.*without a verified",
    ):
        rewrite_legacy_topology_references(payload, mapping)


def test_dispatch_rule_rewrite_rejects_ambiguous_observation_type() -> None:
    """Unknown observation types cannot be guessed from an overlapping integer ID."""

    mapping = HydraulicCompatibilityMapping(
        legacy_node_to_hydraulic_node={1001: 11},
        legacy_segment_to_hydraulic_branch={2001: 21},
        legacy_cross_section_to_hydraulic_cross_section={1001: 31},
    )

    with pytest.raises(
        HydraulicCompatibilityMappingError,
        match="unsupported or missing observation_type",
    ):
        rewrite_legacy_topology_references(
            {
                "dispatch_plan": {
                    "rules": [{
                        "id": 10,
                        "observation_type": "water_level",
                        "observation_object_id": 1001,
                    }]
                }
            },
            mapping,
        )
