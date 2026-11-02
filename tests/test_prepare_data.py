"""Synthetic fixtures only: none of these texts are homework corpus or labels."""

import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from scripts.prepare_data import digest, extract, page_flags, render, save, select_pages, validate


def dataset(root: Path) -> list[dict]:
    (root / "data/texts").mkdir(parents=True)
    (root / "data/raw").mkdir()
    rows = []
    for index in range(30):
        # Deliberately synthetic source bytes: validator verifies hashes, not PDF parsing.
        source = f"Synthetic source {index}".encode()
        pdf_name = f"fixture_{index}.pdf"
        (root / "data/raw" / pdf_name).write_bytes(source)
        pdf_hash = digest(source)
        document_id = "pdf_" + pdf_hash[:20]
        text_id = document_id + "_p001-001"
        text_path = f"data/texts/{text_id}.txt"
        content = f"[PDF_PAGE=1]\nSynthetic fixture {index}; not adventure content.\n".encode()
        (root / text_path).write_bytes(content)
        rows.append(dict(text_id=text_id, document_id=document_id, text_path=text_path,
                         pdf_filename=pdf_name, pdf_pages=[1], pdf_sha256=pdf_hash,
                         text_sha256=digest(content), extraction_method="pypdf_text_layer",
                         source_url=None, author=None, license=None, variant_of=None,
                         split="golden" if index < 10 else "development" if index < 13 else "corpus",
                         adventure_group=document_id, segmentation="synthetic fixture"))
    write_manifest(root, rows)
    return rows


def write_manifest(root, rows):
    (root / "data/manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_valid_dataset(tmp_path):
    dataset(tmp_path)
    assert validate(tmp_path) == []


@pytest.mark.parametrize("defect,expected", [
    ("duplicate", "Duplicate text IDs"),
    ("missing", "Broken or unsafe text path"),
    ("empty", "Empty text"),
    ("changed", "Text hash mismatch"),
    ("split", "Incorrect split counts"),
    ("related", "Related adventure/document crosses splits"),
    ("variant", "Variant split leakage"),
    ("pages", "Page marker mismatch"),
    ("count", "Expected 30 texts"),
])
def test_dataset_rejects_defects(tmp_path, defect, expected):
    rows = dataset(tmp_path)
    if defect == "duplicate":
        rows[1]["text_id"] = rows[0]["text_id"]
    elif defect == "missing":
        (tmp_path / rows[0]["text_path"]).unlink()
    elif defect == "empty":
        (tmp_path / rows[0]["text_path"]).write_text("[PDF_PAGE=1]\n ", encoding="utf-8")
    elif defect == "changed":
        (tmp_path / rows[0]["text_path"]).write_text("[PDF_PAGE=1]\nChanged", encoding="utf-8")
    elif defect == "split":
        rows[0]["split"] = "corpus"
    elif defect == "related":
        rows[10]["adventure_group"] = rows[0]["adventure_group"]
    elif defect == "variant":
        rows[10]["variant_of"] = rows[0]["text_id"]
    elif defect == "pages":
        rows[0]["pdf_pages"] = [2]
    else:
        rows.pop()
    write_manifest(tmp_path, rows)
    assert any(expected in error for error in validate(tmp_path))


def test_stable_identity_and_empty_page_diagnostics(tmp_path):
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    pdf = raw / "z.pdf"
    writer.write(pdf)
    first = extract(pdf, tmp_path)
    # Adding an earlier filename cannot renumber this PDF's identity.
    (raw / "a.pdf").write_bytes(pdf.read_bytes())
    second = extract(pdf, tmp_path)
    assert first["document_id"] == second["document_id"]
    assert first["pages"][0]["pdf_page"] == 1
    assert "empty_text_layer" in first["pages"][0]["flags"]
    assert "[PDF_PAGE=1]" in (tmp_path / first["candidate_path"]).read_text()


def test_preserve_existing_artifacts(tmp_path):
    path = tmp_path / "old.txt"
    save(path, b"original")
    with pytest.raises(ValueError, match="Existing artifact differs"):
        save(path, b"replacement")
    assert path.read_bytes() == b"original"


def test_ocr_review_is_distinct_from_empty_page():
    assert "ocr_review_needed_image_with_little_text" in page_flags("", True, [])
    assert "ocr_review_needed_image_with_little_text" not in page_flags("", False, [])


def test_exact_section_boundaries_preserve_provenance():
    record = {"pages": [{"pdf_page": 1, "text": "Context. Next chapter."},
                        {"pdf_page": 2, "text": "Unused page."},
                        {"pdf_page": 3, "text": "End."}]}
    pages = select_pages(record, [1, 3], {"1": [0, 8]})
    assert render(pages) == "[PDF_PAGE=1]\nContext.\n\n[PDF_PAGE=3]\nEnd.\n"
    assert record["pages"][0]["text"] == "Context. Next chapter."
    with pytest.raises(ValueError, match="offsets"):
        select_pages(record, [1], {"1": [0, 1000]})
    with pytest.raises(ValueError, match="unselected"):
        select_pages(record, [1], {"2": [0, 3]})


def test_pdf_open_errors_are_reported(tmp_path):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"Synthetic malformed PDF fixture")
    record = extract(pdf, tmp_path)
    assert record["errors"][0]["stage"] == "open_pdf"
    assert record["pages"] == []
