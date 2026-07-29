from __future__ import annotations

import pytest

from backend.engine.definition_yaml import (
    DefinitionYamlError,
    dump_definition_yaml,
    load_definition_yaml,
)


def test_multiline_strings_use_literal_block_style_and_round_trip() -> None:
    value = {
        "config": {
            "prompt": "Implement ${TASK}.\n\nRun the tests before finishing.",
        }
    }

    serialized = dump_definition_yaml(value)

    assert "prompt: |-" in serialized
    assert "  Implement ${TASK}." in serialized
    assert load_definition_yaml(serialized) == value


def test_yaml_uses_predictable_string_and_boolean_resolution() -> None:
    parsed = load_definition_yaml(
        "enabled: true\n"
        "disabled: false\n"
        "confirmation: yes\n"
        "switch: on\n"
        "date: 2026-07-29\n"
    )

    assert parsed == {
        "enabled": True,
        "disabled": False,
        "confirmation": "yes",
        "switch": "on",
        "date": "2026-07-29",
    }


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("name: first\nname: second\n", "duplicate mapping keys"),
        ("defaults: &defaults\n  enabled: true\n", "anchors and aliases"),
        ("defaults:\n  <<: {enabled: true}\n", "merge keys"),
        ("id: first\n---\nid: second\n", "exactly one document"),
        ("value: !custom secret\n", "unsupported value or tag"),
    ],
)
def test_unsafe_or_ambiguous_yaml_features_are_rejected(raw: str, message: str) -> None:
    with pytest.raises(DefinitionYamlError, match=message):
        load_definition_yaml(raw)
