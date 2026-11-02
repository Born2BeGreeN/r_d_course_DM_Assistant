"""Prepare blank manual templates or check the read-only golden completion gate."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from urllib.parse import quote

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from scripts.prepare_data import ROOT, digest, save, save_json
from src.dataset import load_snapshot
from src.schema import AdventureCard, card_json_schema

# Deliberately unfinished: language=null is NOT a valid enum answer.
# No source-derived answers, guessed names, or placeholder NPCs are supplied.
BLANK_CARD = {"title": None, "language": None, "recommended_level": None,
              "hook": None, "npcs": [], "locations": [], "threats": [], "rewards": []}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)


def contracts(root: Path) -> dict:
    return {"schema_sha256": digest(json.dumps(card_json_schema(), sort_keys=True, ensure_ascii=False).encode("utf-8")),
            "annotation_guide_sha256": digest((root / "docs/ANNOTATION_GUIDE.md").read_bytes())}


def selection(root: Path) -> list[dict]:
    rows = [json.loads(line, object_pairs_hook=unique_object) for line in (root / "data/manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [r["text_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate manifest IDs (possible golden/development overlap)")
    golden = [r for r in rows if r["split"] == "golden"]
    development = {r["text_id"] for r in rows if r["split"] == "development"}
    golden_ids = {r["text_id"] for r in golden}
    if len(golden) != 10 or golden_ids & development:
        raise ValueError("Expected ten distinct golden IDs, disjoint from development")
    splits = read_json(root / "data/splits.json")
    if set(splits["golden"]) & set(splits["development"]):
        raise ValueError("Golden/development IDs overlap in splits.json")
    if len(splits["golden"]) != 10 or set(splits["golden"]) != golden_ids or set(splits["development"]) != development:
        raise ValueError("Selected splits do not match the manifest")
    # The active OCR revision changed only a corpus input. Never silently annotate
    # against a different golden input revision if this changes later.
    active = {item.text_id: item for item in load_snapshot(root)}
    for row in golden:
        text_path = (root / row["text_path"]).resolve()
        if not text_path.is_relative_to((root / "data/texts").resolve()) or not text_path.is_file():
            raise ValueError(f"Missing/unsafe golden input: {row['text_id']}")
        content = text_path.read_bytes()
        if not content.decode("utf-8").strip() or digest(content) != row["text_sha256"]:
            raise ValueError(f"Empty/changed golden input: {row['text_id']}")
        if row["text_id"] not in active or active[row["text_id"]].split != "golden" or active[row["text_id"]].text_sha256 != row["text_sha256"]:
            raise ValueError(f"Active golden input differs from selected manifest: {row['text_id']}")
    return golden


def prepare(root: Path) -> None:
    rows = selection(root)
    status_path = root / "data/annotation_status.json"
    status = {"manifest_path": "data/manifest.jsonl", "dataset_descriptor_path": "data/active_dataset.json",
              **contracts(root), "annotations": []}
    lines = ["# Індекс ручної golden-анотації", "",
             "Усі нові записи pending. Шаблони не є відповідями і навмисно не проходять schema validation (`language: null`).",
             "Читайте [правила](../../docs/ANNOTATION_GUIDE.md) і [workflow](../../docs/MANUAL_ANNOTATION.md).",
             "Копіюйте шаблон у `data/golden/<text_id>.json`, заповнюйте вручну та лише потім позначайте reviewed у `data/annotation_status.json`.",
             "PDF наведено для provenance; джерелом labels є тільки зв'язаний finalized input, доступний обом моделям.", "",
             "| text_id / шаблон | Вхідний текст | Оригінальний PDF | Фізичні PDF-сторінки (1-based) |", "|---|---|---|---|"]
    for row in rows:
        text_id = row["text_id"]
        save_json(root / f"data/golden_templates/{text_id}.json", BLANK_CARD)
        status["annotations"].append({"text_id": text_id, "input_text_sha256": row["text_sha256"],
                                      "annotation_path": f"data/golden/{text_id}.json", "status": "pending",
                                      "reviewed_by": None, "annotation_sha256": None})
        pages = ", ".join(str(n) for n in row["pdf_pages"])
        pdf = quote(row["pdf_filename"])
        text_link = quote("../" + row["text_path"].removeprefix("data/"))
        lines.append(f"| [{text_id}]({text_id}.json) | [UTF-8 input]({text_link}) | [{row['pdf_filename']}](../raw/{pdf}#page={row['pdf_pages'][0]}) | {pages} |")
    save(root / "data/golden_templates/INDEX.md", ("\n".join(lines) + "\n").encode("utf-8"))
    # A preparation rerun must never reset user review decisions or existing labels.
    if not status_path.exists():
        save_json(status_path, status)
    print(f"Prepared {len(rows)} blank templates; existing labels/status preserved.")


def validate(root: Path) -> dict:
    report = {"complete": False, "selected_count": 0, "completed_count": 0, "counts": {}, "errors": [], "annotations": []}
    try:
        rows = selection(root)
        report["selected_count"] = len(rows)
        status = read_json(root / "data/annotation_status.json")
        for key, value in contracts(root).items():
            if status.get(key) != value:
                report["errors"].append(f"Stale annotation contract: {key}")
        entries = status["annotations"]
        entry_ids = [entry["text_id"] for entry in entries]
        if len(entry_ids) != len(set(entry_ids)):
            report["errors"].append("Duplicate annotation status IDs")
        if set(entry_ids) != {row["text_id"] for row in rows}:
            report["errors"].append("Status IDs do not match selected golden IDs")
        by_id = {entry["text_id"]: entry for entry in entries}
        expected_paths = {f"data/golden/{row['text_id']}.json" for row in rows}
        extras = {p.relative_to(root).as_posix() for p in (root / "data/golden").glob("*.json")} - expected_paths
        if extras:
            report["errors"].append("Unselected annotation files present: " + ", ".join(sorted(extras)))
        for row in rows:
            text_id = row["text_id"]
            entry = by_id.get(text_id, {})
            problems = []
            if entry.get("status") != "reviewed":
                problems.append("not_explicitly_reviewed")
            if not isinstance(entry.get("reviewed_by"), str) or not entry["reviewed_by"].strip():
                problems.append("reviewer_missing")
            if entry.get("input_text_sha256") != row["text_sha256"]:
                problems.append("input_revision_mismatch")
            expected = f"data/golden/{text_id}.json"
            if entry.get("annotation_path") != expected:
                problems.append("annotation_path_must_be_selected_golden_file")
            path = root / expected
            if not path.is_file():
                problems.append("annotation_missing")
            elif not path.resolve().is_relative_to((root / "data/golden").resolve()):
                problems.append("unsafe_annotation_path")
            else:
                raw = path.read_bytes()
                stamp = entry.get("annotation_sha256")
                if not isinstance(stamp, str) or stamp.lower() != digest(raw):
                    problems.append("annotation_not_bound_to_reviewed_bytes")
                try:
                    value = read_json(path)
                    card = AdventureCard.model_validate(value)
                    # A copied template with just language changed is still no annotation.
                    if all(getattr(card, key) in (None, [], "") for key in BLANK_CARD if key != "language"):
                        problems.append("blank_card")
                    strings = [card.title, card.recommended_level, card.hook, *card.locations, *card.threats, *card.rewards,
                               *(npc.name for npc in card.npcs), *(npc.role for npc in card.npcs)]
                    if any(isinstance(value, str) and not value.strip() for value in strings):
                        problems.append("empty_string_placeholder")
                except ValidationError:
                    problems.append("schema_invalid")
                except (ValueError, UnicodeError):
                    problems.append("invalid_json_or_duplicate_keys")
            ready = not problems
            state = "complete" if ready else "pending" if entry.get("status") == "pending" else "incomplete"
            report["annotations"].append({"text_id": text_id, "state": state, "annotation_path": expected, "errors": problems})
        report["counts"] = dict(Counter(a["state"] for a in report["annotations"]))
        report["completed_count"] = sum(a["state"] == "complete" for a in report["annotations"])
        report["complete"] = not report["errors"] and report["completed_count"] == 10
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        report["errors"].append(str(exc))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    gate = sub.add_parser("validate")
    gate.add_argument("--report", type=Path)
    hash_command = sub.add_parser("hash")
    hash_command.add_argument("annotation", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(ROOT)
            return 0
        if args.command == "hash":
            print(digest(args.annotation.read_bytes()))
            return 0
        report = validate(ROOT)
        if args.report:
            save_json(args.report, report)
        print(f"Golden completion gate: {'PASS' if report['complete'] else 'NOT READY'}; "
              f"completed={report['completed_count']}/{report['selected_count']}; counts={report['counts']}")
        for entry in report["annotations"]:
            print(f"{entry['text_id']}: {entry['state']} ({', '.join(entry['errors']) or 'OK'})")
        for error in report["errors"]:
            print(error, file=sys.stderr)
        return 0 if report["complete"] else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
