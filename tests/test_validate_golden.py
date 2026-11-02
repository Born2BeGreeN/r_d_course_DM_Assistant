"""Synthetic temporary inputs/labels only; never writes real golden annotations."""

import json
from pathlib import Path

import pytest

from scripts.prepare_data import digest
from scripts.validate_golden import BLANK_CARD, prepare, validate


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    rows = []
    for n in range(13):
        text_id = f"synthetic_{n:02d}"
        path = tmp_path / f"data/texts/{text_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"Synthetic input {n}; not adventure content.".encode())
        rows.append(dict(text_id=text_id, text_path=path.relative_to(tmp_path).as_posix(),
                         text_sha256=digest(path.read_bytes()), split="golden" if n < 10 else "development",
                         pdf_pages=[1, 2], pdf_filename=f"Synthetic PDF {n}.pdf"))
    manifest = tmp_path / "data/manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    write(tmp_path / "data/active_dataset.json", {"manifest_path": "data/manifest.jsonl", "manifest_sha256": digest(manifest.read_bytes())})
    write(tmp_path / "data/splits.json", {"golden": [r["text_id"] for r in rows[:10]], "development": [r["text_id"] for r in rows[10:]]})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/ANNOTATION_GUIDE.md").write_text("Synthetic rules fixture", encoding="utf-8")
    prepare(tmp_path)
    return tmp_path


def finish_synthetic_annotations(root):
    status_path = root / "data/annotation_status.json"
    status = json.loads(status_path.read_text())
    for entry in status["annotations"]:
        path = root / entry["annotation_path"]
        write(path, BLANK_CARD | {"title": "Synthetic test title", "language": "en"})
        entry.update(status="reviewed", reviewed_by="Synthetic test reviewer", annotation_sha256=digest(path.read_bytes()))
    write(status_path, status)
    return status


def test_pending_templates_never_complete_gate(root):
    report = validate(root)
    assert not report["complete"]
    assert report["counts"] == {"pending": 10}
    assert report["completed_count"] == 0
    assert len(list((root / "data/golden_templates").glob("*.json"))) == 10
    assert not list((root / "data/golden").glob("*.json"))


def test_valid_reviewed_files_pass_without_modification(root):
    finish_synthetic_annotations(root)
    before = {p: p.read_bytes() for p in (root / "data/golden").glob("*.json")}
    assert validate(root)["complete"] is True
    prepare(root)  # Never resets reviewed status or changes labels.
    assert validate(root)["complete"] is True
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize("defect,expected", [
    ("pending", "not_explicitly_reviewed"),
    ("reviewer", "reviewer_missing"),
    ("hash", "annotation_not_bound_to_reviewed_bytes"),
    ("input_hash", "input_revision_mismatch"),
    ("template", "schema_invalid"),
    ("empty", "blank_card"),
    ("malformed", "schema_invalid"),
    ("template_path", "annotation_path_must_be_selected_golden_file"),
    ("duplicate_keys", "invalid_json_or_duplicate_keys"),
])
def test_completion_gate_rejects_incomplete_or_stale_annotations(root, defect, expected):
    status = finish_synthetic_annotations(root)
    entry = status["annotations"][0]
    path = root / entry["annotation_path"]
    if defect == "pending":
        entry["status"] = "pending"
    elif defect == "reviewer":
        entry["reviewed_by"] = None
    elif defect == "hash":
        path.write_bytes(path.read_bytes() + b" ")
    elif defect == "input_hash":
        entry["input_text_sha256"] = "0" * 64
    elif defect == "template":
        write(path, BLANK_CARD)
    elif defect == "empty":
        write(path, BLANK_CARD | {"language": "unknown"})
    elif defect == "malformed":
        write(path, {"title": "Synthetic title"})
    elif defect == "template_path":
        entry["annotation_path"] = f"data/golden_templates/{entry['text_id']}.json"
    else:
        path.write_text('{"title":null,"title":"duplicate"}', encoding="utf-8")
    if defect in {"template", "empty", "malformed", "duplicate_keys"}:
        entry["annotation_sha256"] = digest(path.read_bytes())
    write(root / "data/annotation_status.json", status)
    report = validate(root)
    assert not report["complete"]
    assert expected in report["annotations"][0]["errors"]


def test_golden_development_overlap_blocks_gate(root):
    splits = json.loads((root / "data/splits.json").read_text())
    splits["development"].append(splits["golden"][0])
    write(root / "data/splits.json", splits)
    report = validate(root)
    assert not report["complete"]
    assert any("overlap" in error for error in report["errors"])


def test_changed_contract_requires_review(root):
    finish_synthetic_annotations(root)
    (root / "docs/ANNOTATION_GUIDE.md").write_text("Changed synthetic rules")
    assert "Stale annotation contract: annotation_guide_sha256" in validate(root)["errors"]
