"""Synthetic OCR fixtures only; never invokes Windows OCR or a model."""

import json
from pathlib import Path
import subprocess

import pytest

from scripts import ocr_fallback as ocr
from scripts.prepare_data import digest, render, save_json
from src.dataset import load_snapshot


def flagged(document_id="pdf_fixture"):
    return {"documents": [{"document_id": document_id, "pdf_filename": "fixture.pdf",
                            "page_diagnostics": [
                                {"pdf_page": 1, "flags": ["ocr_review_needed_image_with_little_text"]},
                                {"pdf_page": 2, "flags": ["sparse_text_layer_review"]},
                            ]}]}


def test_only_previously_flagged_pages_are_ocr_targets():
    assert [(d["document_id"], n) for d, n in ocr.targets(flagged())] == [("pdf_fixture", 1)]


def fixture(root):
    source = b"Synthetic PDF fixture; never used as real corpus."
    source_hash = digest(source)
    doc = "pdf_" + source_hash[:20]
    source_path = root / "data/raw/fixture.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source)
    diagnostics = flagged(doc)
    diagnostics["documents"][0]["pdf_sha256"] = source_hash
    save_json(root / "data/preparation_diagnostics.json", diagnostics)
    pages = [{"pdf_page": 1, "text": "1\n", "characters": 2, "flags": ["ocr_review_needed_image_with_little_text"]}]
    candidate = render(pages).encode()
    base = {"document_id": doc, "pdf_filename": "fixture.pdf", "pdf_sha256": source_hash,
            "pages": pages, "candidate_sha256": digest(candidate), "extraction_method": "pypdf_text_layer"}
    save_json(root / f"data/extracted/{doc}.json", base)
    (root / f"data/extracted/{doc}.txt").write_bytes(candidate)
    text_path = f"data/texts/{doc}.txt"
    (root / "data/texts").mkdir()
    (root / text_path).write_bytes(candidate)
    row = dict(text_id=doc, document_id=doc, text_path=text_path, text_sha256=digest(candidate),
               candidate_sha256=digest(candidate), pdf_filename="fixture.pdf", pdf_sha256=source_hash,
               pdf_pages=[1], split="corpus", quality_flags=[], segmentation={"page_slices": {}})
    manifest = root / "data/manifest.jsonl"
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")
    raw_path = root / "data/ocr/synthetic/ocr.json"
    raw_path.parent.mkdir(parents=True)
    text = "Synthetic scene.\nUnreadable map noise."
    (raw_path.parent / "text.txt").write_bytes(text.encode())
    image = b"Synthetic image fixture"
    (raw_path.parent / "page.png").write_bytes(image)
    raw = dict(document_id=doc, pdf_page=1, pdf_sha256=source_hash, status="needs_review",
               lines=text.splitlines(), ocr_text_sha256=digest(text.encode()), image_sha256=digest(image),
               tool="Synthetic OCR", tool_version="fixture-only", language="en-US")
    save_json(raw_path, raw)
    review = {"source_manifest_sha256": digest(manifest.read_bytes()), "pages": [
        dict(document_id=doc, pdf_page=1, record_path=raw_path.relative_to(root).as_posix(),
             record_sha256=digest(raw_path.read_bytes()), decision="partial_unresolved", accepted_lines=[1],
             accepted_text="Synthetic scene.", reason="Synthetic test review")
    ]}
    review_path = root / "data/review.json"
    save_json(review_path, review)
    return doc, review_path


def test_revision_preserves_originals_labels_and_shared_input_bytes(tmp_path, monkeypatch):
    doc, review = fixture(tmp_path)
    label = tmp_path / "data/golden/reviewed.json"
    label.parent.mkdir()
    label.write_bytes(b'{"synthetic_manually_reviewed_fixture":true}')
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    # Count/split validator has its own 30-record tests and is run on the real revision.
    monkeypatch.setattr(ocr, "validate", lambda *args, **kwargs: [])
    output = tmp_path / "data/ocr_revisions/test-v1"
    ocr.revise(tmp_path, review, output, activate=True)
    assert all(p.read_bytes() == content for p, content in before.items())
    assert list((output / "texts").glob("*.txt")) == [output / "texts" / f"{doc}.txt"]
    provider_inputs = load_snapshot(tmp_path)
    local_inputs = load_snapshot(tmp_path)
    assert provider_inputs == local_inputs
    assert provider_inputs[0].content == "[PDF_PAGE=1]\nSynthetic scene.\n1\n\n"
    ocr.revise(tmp_path, review, output, activate=True)  # Idempotent, no overwrite.
    path = output / "texts" / f"{doc}.txt"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Input hash mismatch"):
        load_snapshot(tmp_path)


@pytest.mark.parametrize("defect", ["invented_text", "stale_review", "unflagged", "changed_image"])
def test_revision_rejects_unverified_ocr(tmp_path, monkeypatch, defect):
    _, review_path = fixture(tmp_path)
    review = json.loads(review_path.read_text())
    if defect == "invented_text":
        review["pages"][0]["accepted_text"] = "Invented source content"
    elif defect == "stale_review":
        review["source_manifest_sha256"] = "0" * 64
    elif defect == "unflagged":
        review["pages"][0]["pdf_page"] = 2
    else:
        (tmp_path / "data/ocr/synthetic/page.png").write_bytes(b"changed image")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    monkeypatch.setattr(ocr, "validate", lambda *args, **kwargs: [])
    with pytest.raises(ValueError):
        ocr.revise(tmp_path, review_path, tmp_path / "data/ocr_revisions/test-v1")
    assert not (tmp_path / "data/active_dataset.json").exists()


def test_local_ocr_timeout_is_unresolved_not_success(tmp_path, monkeypatch):
    doc, _ = fixture(tmp_path)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("synthetic OCR", 120)
    monkeypatch.setattr(ocr, "windows_ocr", timeout)
    report = tmp_path / "data/ocr_timeout.json"
    ocr.run(tmp_path, tmp_path / "data/ocr/timeout", report, doc, 1, {}, {})
    assert json.loads(report.read_text())["counts"] == {"unresolved": 1}


def test_shared_loader_rejects_manifest_changes(tmp_path):
    fixture(tmp_path)
    save_json(tmp_path / "data/active_dataset.json", {"manifest_path": "data/manifest.jsonl", "manifest_sha256": "0" * 64})
    with pytest.raises(ValueError, match="Manifest hash mismatch"):
        load_snapshot(tmp_path)
