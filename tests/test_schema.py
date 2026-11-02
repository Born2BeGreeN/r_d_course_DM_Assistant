"""Synthetic card fixtures only, outside the real corpus and manual golden set."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schema import AdventureCard, card_json_schema, export_json_schema

# Invented solely for structural tests; never a source annotation or measurement.
SYNTHETIC_CARD = {
    "title": "Synthetic Lantern Errand",
    "language": "en",
    "recommended_level": "for 2nd-level characters",
    "hook": "A lantern keeper asks the visitors to find a missing bell.",
    "npcs": [{"name": "Synthetic Keeper", "role": "lantern keeper"}],
    "locations": ["Synthetic Pier"],
    "threats": ["a flooded stairway"],
    "rewards": ["three silver tokens"],
}


def test_valid_card_round_trips_json():
    card = AdventureCard.model_validate_json(json.dumps(SYNTHETIC_CARD))
    assert json.loads(card.model_dump_json()) == SYNTHETIC_CARD


def test_explicit_nulls_empty_lists_and_null_npc_role_are_valid():
    value = {"title": None, "language": "unknown", "recommended_level": None,
             "hook": None, "npcs": [], "locations": [], "threats": [], "rewards": []}
    assert AdventureCard.model_validate(value).model_dump() == value
    value["npcs"] = [{"name": "Synthetic Name", "role": None}]
    assert AdventureCard.model_validate(value).npcs[0].role is None


def test_invalid_language_is_rejected():
    value = deepcopy(SYNTHETIC_CARD)
    value["language"] = "it"
    with pytest.raises(ValidationError) as error:
        AdventureCard.model_validate(value)
    assert error.value.errors()[0]["loc"] == ("language",)
    assert error.value.errors()[0]["type"] == "literal_error"


@pytest.mark.parametrize("key", list(SYNTHETIC_CARD))
def test_every_top_level_key_is_required(key):
    value = deepcopy(SYNTHETIC_CARD)
    del value[key]
    with pytest.raises(ValidationError) as error:
        AdventureCard.model_validate(value)
    assert any(e["loc"] == (key,) and e["type"] == "missing" for e in error.value.errors())


@pytest.mark.parametrize("npc,location", [
    ({"role": "synthetic role"}, ("npcs", 0, "name")),
    ({"name": "Synthetic Name"}, ("npcs", 0, "role")),
    ({"name": 123, "role": None}, ("npcs", 0, "name")),
    ({"name": "Synthetic Name", "role": ["synthetic role"]}, ("npcs", 0, "role")),
])
def test_malformed_npc_is_rejected(npc, location):
    value = deepcopy(SYNTHETIC_CARD)
    value["npcs"] = [npc]
    with pytest.raises(ValidationError) as error:
        AdventureCard.model_validate(value)
    assert any(e["loc"] == location for e in error.value.errors())


@pytest.mark.parametrize("nested", [False, True])
def test_extra_properties_and_metadata_are_rejected_at_both_levels(nested):
    value = deepcopy(SYNTHETIC_CARD)
    target = value["npcs"][0] if nested else value
    target["pdf_page"] = 1
    with pytest.raises(ValidationError) as error:
        AdventureCard.model_validate_json(json.dumps(value))
    assert any(e["type"] == "extra_forbidden" for e in error.value.errors())


def test_list_items_are_strings_without_numeric_coercion():
    value = deepcopy(SYNTHETIC_CARD)
    value["rewards"] = [50]
    with pytest.raises(ValidationError):
        AdventureCard.model_validate(value)


def test_exported_schema_is_the_same_required_contract_for_both_adapters(tmp_path):
    output = tmp_path / "card.schema.json"
    export_json_schema(output)
    schema = json.loads(output.read_text(encoding="utf-8"))
    assert schema == card_json_schema()
    assert set(schema["properties"]) == set(SYNTHETIC_CARD)
    assert set(schema["required"]) == set(SYNTHETIC_CARD)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["language"]["enum"] == ["en", "uk", "mixed", "other", "unknown"]
    npc = schema["$defs"]["NPC"]
    assert set(npc["required"]) == {"name", "role"}
    assert npc["additionalProperties"] is False
    assert all("description" in field for field in schema["properties"].values())
    checked_in = Path(__file__).resolve().parents[1] / "docs/adventure_card.schema.json"
    assert json.loads(checked_in.read_text(encoding="utf-8")) == schema
