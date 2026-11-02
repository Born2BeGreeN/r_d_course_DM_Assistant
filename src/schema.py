"""Shared Pydantic v2 card and JSON Schema for both extraction adapters.

Validation checks structure, not factual grounding. Source evidence, dataset
identity, usage, latency, and other execution metadata belong outside this card.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["en", "uk", "mixed", "other", "unknown"]


class NPC(BaseModel):
    """A named, story-relevant non-player actor explicitly present in the input."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(
        ...,
        description="Original explicit name of a story-relevant NPC, including named animals or creatures. "
        "Preserve source language and spelling; use the first unambiguous full name, not a translation. "
        "Do not invent names for anonymous groups or add historical cameos/deities mentioned only as references.",
    )
    role: str | None = Field(
        ...,
        description="One short source phrase explicitly describing this NPC's role, in the source language. "
        "Use the earliest clear role phrase; null if unstated. Do not infer alignment, class, motives, "
        "or relationships from D&D knowledge or another adventure.",
    )


class AdventureCard(BaseModel):
    """Eight required keys; missing facts use explicit null or empty lists."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "description": "Extract only facts explicitly present in the supplied finalized text. "
            "Keep original names and source language; use short source phrases without translation or invention. "
            "Never supply missing OCR text or infer facts from other adventures or D&D knowledge. "
            "All eight keys are required even when null or empty. Deduplicate entities in source order. "
            "Keep provenance, evidence notes, and execution metadata outside the generated card."
        },
    )

    title: str | None = Field(
        ...,
        description="Explicit adventure title in its original source language and spelling. "
        "Prefer the first clear adventure title over a generic section heading; null if absent. "
        "Do not infer a title from a filename, metadata, or another adventure.",
    )
    language: Language = Field(
        ...,
        description="Natural language of the supplied narrative: en for English, uk for Ukrainian, "
        "mixed for substantive passages in two or more natural languages, other for another single language, "
        "unknown when reliable classification is impossible. Proper names, D&D terms, credits, "
        "and isolated foreign words do not make the text mixed.",
    )
    recommended_level: str | None = Field(
        ...,
        description="Short original source phrase explicitly recommending player-character levels for this "
        "adventure or selected scene; preserve any range or condition. Null if not directly stated. "
        "Never substitute ages, edition numbers, NPC/class/spell levels, challenge ratings, or levels "
        "of a referenced attraction/adventure; never calculate or infer a recommendation.",
    )
    hook: str | None = Field(
        ...,
        description="One short complete source sentence stating the inciting incident, objective, or reason "
        "to engage (at most 40 whitespace-separated words). Preserve source language and original names. "
        "Choose the first qualifying sentence in source order; null if none. Do not summarize, "
        "join multiple sentences, truncate a sentence, or invent missing OCR words.",
    )
    npcs: list[NPC] = Field(
        ...,
        description="Named NPCs explicitly relevant to the supplied story, including offstage antagonists "
        "and named animals when their narrative role is explicit. Deduplicate clear aliases, keep the first "
        "unambiguous full original name, and order by first entity mention. Exclude player characters, "
        "anonymous groups, authors, and reference-only cameos. Use [] when none are supported.",
    )
    locations: list[str] = Field(
        ...,
        description="Short original source names or phrases for settings, destinations, or explorable areas "
        "explicitly relevant to this story. Keep source language; deduplicate in first-mention order. "
        "Do not add places from background knowledge or unrelated references. Use [] if absent.",
    )
    threats: list[str] = Field(
        ...,
        description="Short source phrases naming explicit current-story dangers, hostile actors, traps, "
        "or harmful conditions. Preserve original names, source language, and necessary conditional wording. "
        "Do not turn historical boasts, speculation, or monster knowledge into threats. Deduplicate in "
        "source order; use [] if absent.",
    )
    rewards: list[str] = Field(
        ...,
        description="Short source phrases for explicitly promised/earned benefits or discoverable collectible "
        "loot, retaining stated quantities and conditions in the source language. Exclude starting equipment, "
        "shop prices/items merely for sale, decorations, and inferred treasure. Deduplicate in source order; "
        "use [] if absent.",
    )


def card_json_schema() -> dict:
    """Return a fresh, provider-neutral JSON Schema; both adapters use this contract."""
    return AdventureCard.model_json_schema(mode="validation")


def export_json_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the shared AdventureCard JSON Schema; no model calls.")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "docs/adventure_card.schema.json")
    export_json_schema(parser.parse_args().output)


if __name__ == "__main__":
    main()
