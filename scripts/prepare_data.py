"""Offline, lossless PDF text-layer preparation. This script does not perform OCR."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import logging
from pathlib import Path
import re
import sys
import unicodedata
import warnings

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
METHOD = "pypdf_text_layer"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(path: Path, data: bytes) -> None:
    """Never silently replace an earlier source, label, or preparation artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Existing artifact differs; use a new output path: {path}")
        return
    path.write_bytes(data)


def save_json(path: Path, value: object) -> None:
    save(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def render(pages: list[dict]) -> str:
    return "\n\n".join(f"[PDF_PAGE={p['pdf_page']}]\n{p['text']}" for p in pages) + "\n"


def select_pages(record: dict, numbers: list[int], slices: dict) -> list[dict]:
    pages = []
    for n in numbers:
        if type(n) is not int or not 1 <= n <= len(record["pages"]):
            raise ValueError("PDF page out of bounds")
        page = dict(record["pages"][n - 1])
        start, end = slices.get(str(n), [0, len(page["text"])])
        if not 0 <= start < end <= len(page["text"]) and not (start == end == 0):
            raise ValueError("Invalid source character offsets")
        page["text"] = page["text"][start:end]
        pages.append(page)
    if set(slices) - {str(n) for n in numbers}:
        raise ValueError("Slice references an unselected page")
    return pages


def page_flags(text: str, has_images: bool, positions: list[tuple]) -> list[str]:
    flags = []
    if not text.strip():
        flags.append("empty_text_layer")
    if len(re.sub(r"\s", "", text)) < 40 and has_images:
        flags.append("ocr_review_needed_image_with_little_text")
    if "\ufffd" in text or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        flags.append("suspicious_glyph_encoding")
    if any(unicodedata.category(c) == "Co" for c in text):
        flags.append("private_use_font_glyphs")
    if re.search(r"(.{6,50})\1{2,}", text):
        flags.append("repeated_text_runs")
    if text.strip() and sum(c.isalpha() for c in text) < 120:
        flags.append("sparse_text_layer_review")
    if re.search(r"\w-\s*\n\w", text):
        flags.append("line_break_hyphenation")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 30 and sum(len(line) < 25 for line in lines) / len(lines) > .5:
        flags.append("suspicious_reading_order_short_lines")
    # Content-stream x resets across columns can indicate interleaved reading order.
    # These are review flags, never a claim that the order is certainly wrong.
    resets = sum(a[0] - b[0] > 100 and abs(a[1] - b[1]) < 30
                 for a, b in zip(positions, positions[1:]))
    if resets >= 3:
        flags.append("suspicious_reading_order_column_resets")
    return flags


def extract(pdf: Path, root: Path) -> dict:
    pdf_hash = digest(pdf.read_bytes())
    document_id = f"pdf_{pdf_hash[:20]}"
    record = {"document_id": document_id, "pdf_filename": pdf.name,
              "pdf_sha256": pdf_hash, "extraction_method": METHOD,
              "author": None, "source_url": None, "license": None,
              "pages": [], "errors": [], "warnings": []}
    class LogCapture(logging.Handler):
        def emit(self, event):
            # pypdf diagnostics use logging as well as Python warnings.
            message = re.sub(r"IndirectObject\((\d+), (\d+), \d+\)", r"IndirectObject(\1, \2, <reader>)", event.getMessage())
            record["warnings"].append(message)

    logger = logging.getLogger("pypdf")
    capture = LogCapture()
    logger.addHandler(capture)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            reader = PdfReader(pdf)
            metadata = reader.metadata
            record["metadata"] = {key: str(value) for key, value in (metadata or {}).items()}
            record["author"] = str(metadata.author).strip() if metadata and metadata.author else None
            for number, page in enumerate(reader.pages, 1):
                positions = []
                try:
                    def visit(text, cm, tm, font, size):
                        if text.strip():
                            positions.append((tm[4], tm[5]))
                    text = page.extract_text(visitor_text=visit) or ""
                    try:
                        has_images = bool(page.images)
                    except Exception as exc:
                        has_images = False
                        record["errors"].append({"pdf_page": number, "stage": "image_inspection", "error": str(exc)})
                    flags = page_flags(text, has_images, positions)
                    record["pages"].append({"pdf_page": number, "text": text,
                                             "characters": len(text), "flags": flags})
                except Exception as exc:
                    record["errors"].append({"pdf_page": number, "stage": "text_extraction", "error": str(exc)})
                    record["pages"].append({"pdf_page": number, "text": "", "characters": 0,
                                             "flags": ["extraction_error", "ocr_or_pdf_repair_review_needed"]})
        except Exception as exc:
            record["errors"].append({"pdf_page": None, "stage": "open_pdf", "error": str(exc)})
        record["warnings"] = sorted(set(record["warnings"] + [str(w.message) for w in caught]))
    logger.removeHandler(capture)
    candidate = render(record["pages"]).encode("utf-8")
    record["candidate_sha256"] = digest(candidate)
    record["candidate_path"] = f"data/extracted/{document_id}.txt"
    save(root / record["candidate_path"], candidate)
    save_json(root / f"data/extracted/{document_id}.json", record)
    return record


def extract_many(root: Path, names: list[str], report_path: Path) -> None:
    files = sorted((root / "data/raw").glob("*.pdf"))
    if names:
        requested = set(names)
        files = [p for p in files if p.name in requested]
        if requested != {p.name for p in files}:
            raise ValueError("Requested PDF not found")
    records = []
    for pdf in files:
        raw_hash = digest(pdf.read_bytes())
        cache = root / f"data/extracted/pdf_{raw_hash[:20]}.json"
        if cache.exists():
            record = json.loads(cache.read_text(encoding="utf-8"))
            if record["pdf_sha256"] != raw_hash or record["pdf_filename"] != pdf.name:
                raise ValueError("Hash collision or renamed cached PDF; review provenance")
            if digest((root / record["candidate_path"]).read_bytes()) != record["candidate_sha256"]:
                raise ValueError("Changed extraction cache")
            if digest(render(record["pages"]).encode("utf-8")) != record["candidate_sha256"]:
                raise ValueError("Changed cached source pages")
        else:
            record = extract(pdf, root)
        # Recompute text-only diagnostics for cached pilot pages without rewriting evidence.
        for page in record["pages"]:
            page["flags"] = sorted(set(page["flags"] + page_flags(page["text"], False, [])))
        records.append(record)
        print(f"{record['document_id']} pages={len(record['pages'])} chars={sum(p['characters'] for p in record['pages'])} {pdf.name}", flush=True)
    summary = []
    for record in records:
        summary.append({key: value for key, value in record.items() if key != "pages"} | {
            "page_count": len(record["pages"]),
            "characters": sum(p["characters"] for p in record["pages"]),
            "page_diagnostics": [{key: value for key, value in p.items() if key != "text"} for p in record["pages"]],
        })
    save_json(report_path, {"extraction_method": METHOD, "ocr_performed": False,
                           "diagnostics_policy": "Heuristic review flags, not verified OCR need or reading-order defects. Image-only maps/covers may need no OCR for this task.",
                           "document_count": len(records), "documents": summary})


def build(root: Path, selection: Path) -> None:
    choices = json.loads(selection.read_text(encoding="utf-8"))
    rows = []
    for choice in choices:
        record = json.loads((root / f"data/extracted/{choice['document_id']}.json").read_text(encoding="utf-8"))
        numbers = choice["pdf_pages"]
        if not numbers or numbers != sorted(set(numbers)):
            raise ValueError("Pages must be distinct, ascending, and 1-based")
        slices = choice["segmentation"].get("page_slices", {})
        pages = select_pages(record, numbers, slices)
        if len(pages) != len(numbers) or any(p["pdf_page"] != n for p, n in zip(pages, numbers)):
            raise ValueError("Invalid page range")
        if not any(p["text"].strip() for p in pages):
            raise ValueError("Cannot count empty pages as an example")
        text_id = f"{record['document_id']}_p{numbers[0]:03d}-{numbers[-1]:03d}"
        if numbers != list(range(numbers[0], numbers[-1] + 1)):
            text_id += "_" + digest(json.dumps(numbers).encode())[:8]
        if slices:
            text_id += "_" + digest(json.dumps(slices, sort_keys=True).encode())[:8]
        text_path = f"data/texts/{text_id}.txt"
        content = render(pages).encode("utf-8")
        row = {"text_id": text_id, "document_id": record["document_id"], "text_path": text_path,
               "pdf_filename": record["pdf_filename"], "pdf_pages": numbers,
               "pdf_sha256": record["pdf_sha256"], "text_sha256": digest(content),
               "candidate_sha256": record["candidate_sha256"], "extraction_method": METHOD,
               "source_url": choice.get("source_url", record["source_url"]),
               "author": choice.get("author", record["author"]),
               "author_evidence": choice.get("author_evidence", "PDF metadata /Author; unverified attribution" if record["author"] else None),
               "license": choice.get("license", record["license"]),
               "license_evidence": choice.get("license_evidence"),
               "variant_of": choice.get("variant_of"), "split": choice["split"],
               "adventure_group": choice["adventure_group"], "segmentation": choice["segmentation"],
               "quality_flags": sorted({f for p in pages for f in p["flags"] + page_flags(p["text"], False, [])}),
               "characters": len(content.decode("utf-8")), "words": len(" ".join(p["text"] for p in pages).split())}
        save(root / text_path, content)
        rows.append(row)
    # Preserve manual selection ordering and never overwrite a previous different manifest.
    manifest = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    manifest_path = root / "data/manifest.jsonl"
    existing = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()] if manifest_path.exists() else None
    if existing != rows:
        save(manifest_path, manifest.encode("utf-8"))
    errors = validate(root)
    if errors:
        raise ValueError("; ".join(errors))
    save_json(root / "data/splits.json", {split: [r["text_id"] for r in rows if r["split"] == split]
                                         for split in ("golden", "development", "corpus")})
    print(f"Built {len(rows)} texts; splits={dict(Counter(r['split'] for r in rows))}")


def validate(root: Path, expected_count: int = 30, manifest_path: Path | None = None) -> list[str]:
    errors = []
    try:
        rows = [json.loads(line) for line in (manifest_path or root / "data/manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        return [f"Manifest unreadable: {exc}"]
    ids = [r.get("text_id") for r in rows]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate text IDs")
    if len(rows) != expected_count:
        errors.append(f"Expected {expected_count} texts; got {len(rows)}")
    counts = Counter(r.get("split") for r in rows)
    if counts != Counter({"golden": 10, "development": 3, "corpus": expected_count - 13}):
        errors.append(f"Incorrect split counts: {dict(counts)}")
    grouping = defaultdict(set)
    seen_paths, seen_content = set(), set()
    for row in rows:
        required = {"text_id", "document_id", "text_path", "pdf_filename", "pdf_pages", "pdf_sha256", "text_sha256", "extraction_method", "source_url", "author", "license", "variant_of", "split", "adventure_group", "segmentation"}
        if not required <= row.keys():
            errors.append(f"Missing manifest fields: {row.get('text_id')}")
            continue
        for group in (row["adventure_group"], row["document_id"], row["pdf_sha256"]):
            grouping[group].add(row["split"])
        if row["variant_of"]:
            if row["variant_of"] not in ids:
                errors.append(f"Unknown variant parent: {row['text_id']}")
            else:
                parent = next(r for r in rows if r["text_id"] == row["variant_of"])
                if parent["split"] != row["split"]:
                    errors.append(f"Variant split leakage: {row['text_id']}")
        path = (root / row["text_path"]).resolve()
        allowed = path.is_relative_to((root / "data/texts").resolve())
        if manifest_path is not None:
            allowed = allowed or path.is_relative_to((manifest_path.parent / "texts").resolve())
        if not allowed or not path.is_file():
            errors.append(f"Broken or unsafe text path: {row['text_path']}")
            continue
        if path in seen_paths:
            errors.append(f"Duplicate text path: {path.name}")
        seen_paths.add(path)
        content = path.read_bytes()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"Not UTF-8: {path.name}")
            continue
        if not re.sub(r"\[PDF_PAGE=\d+\]", "", text).strip():
            errors.append(f"Empty text: {path.name}")
        if digest(content) != row["text_sha256"]:
            errors.append(f"Text hash mismatch: {path.name}")
        normalized = re.sub(r"\s+", " ", re.sub(r"\[PDF_PAGE=\d+\]", "", text)).strip()
        if normalized in seen_content:
            errors.append(f"Duplicate content: {path.name}")
        seen_content.add(normalized)
        numbers = row["pdf_pages"]
        if not numbers or any(type(n) is not int or n < 1 for n in numbers) or numbers != sorted(set(numbers)):
            errors.append(f"Invalid PDF pages: {path.name}")
        if [int(n) for n in re.findall(r"\[PDF_PAGE=(\d+)\]", text)] != numbers:
            errors.append(f"Page marker mismatch: {path.name}")
        if row["document_id"] != f"pdf_{row['pdf_sha256'][:20]}":
            errors.append(f"Document identity mismatch: {path.name}")
        pdf = root / "data/raw" / row["pdf_filename"]
        if not pdf.is_file():
            errors.append(f"Missing local original PDF: {pdf.name}")
        elif digest(pdf.read_bytes()) != row["pdf_sha256"]:
            errors.append(f"PDF hash mismatch: {pdf.name}")
        cache = root / row.get("candidate_metadata_path", f"data/extracted/{row['document_id']}.json")
        if cache.exists():
            source = json.loads(cache.read_text(encoding="utf-8"))
            candidate = root / row.get("candidate_path", f"data/extracted/{row['document_id']}.txt")
            if not candidate.is_file() or digest(candidate.read_bytes()) != row.get("candidate_sha256"):
                errors.append(f"Candidate hash mismatch or missing candidate: {path.name}")
            if digest(render(source["pages"]).encode("utf-8")) != row.get("candidate_sha256"):
                errors.append(f"Cached source page hash mismatch: {path.name}")
            try:
                slices = row["segmentation"].get("page_slices", {}) if isinstance(row["segmentation"], dict) else {}
                if render(select_pages(source, numbers, slices)) != text:
                    errors.append(f"Text differs from source pages: {path.name}")
            except (IndexError, TypeError, ValueError):
                errors.append(f"PDF page out of bounds: {path.name}")
    if any(len(splits) > 1 for splits in grouping.values()):
        errors.append("Related adventure/document crosses splits")
    actual = {p.resolve() for p in (root / "data/texts").glob("*.txt")}
    if manifest_path is None and actual != seen_paths:
        errors.append("Text files and manifest paths differ")
    split_path = root / "data/splits.json"
    if split_path.exists():
        expected = {s: [r["text_id"] for r in rows if r["split"] == s] for s in ("golden", "development", "corpus")}
        if json.loads(split_path.read_text(encoding="utf-8")) != expected:
            errors.append("splits.json differs from manifest")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    extraction = sub.add_parser("extract")
    extraction.add_argument("--pdf", action="append", default=[])
    extraction.add_argument("--report", type=Path, required=True)
    selection = sub.add_parser("build")
    selection.add_argument("--selection", type=Path, default=ROOT / "data/selection.json")
    validation = sub.add_parser("validate")
    validation.add_argument("--report", type=Path)
    validation.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "extract":
            extract_many(ROOT, args.pdf, args.report)
        elif args.command == "build":
            build(ROOT, args.selection)
        else:
            errors = validate(ROOT, manifest_path=args.manifest)
            if args.report:
                save_json(args.report, {"valid": not errors, "errors": errors,
                                        "manifest_sha256": digest((args.manifest or ROOT / "data/manifest.jsonl").read_bytes())})
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print("Dataset valid: 30 non-empty texts; golden=10, development=3, corpus=17")
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
