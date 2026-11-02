"""Local Windows OCR for previously flagged pages; immutable outputs and revisions."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.prepare_data import ROOT, digest, render, save, save_json, select_pages, validate

# WinRT is called with ordinary PowerShell commands; no execution-policy flags,
# administrator actions, downloads, or external services are used.
WINDOWS_COMMAND = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType=WindowsRuntime]
$null = [Windows.Data.Pdf.PdfPageRenderOptions, Windows.Data.Pdf, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapTransform, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$version = [Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $env:WINDIR 'System32\Windows.Media.Ocr.dll')).FileVersion
$languages = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
$info = @{tool='Windows.Media.Ocr'; tool_version=$version; os_version=[Environment]::OSVersion.Version.ToString(); available_languages=$languages; renderer='Windows.Data.Pdf'; renderer_version=[Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $env:WINDIR 'System32\Windows.Data.Pdf.dll')).FileVersion}
if ($env:ADVENTURE_OCR_PROBE -eq '1') { $info | ConvertTo-Json -Depth 6 -Compress; exit 0 }
$language = New-Object Windows.Globalization.Language($env:ADVENTURE_OCR_LANGUAGE)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
if ($null -eq $engine) { $info.status='unresolved'; $info.reason='language_unavailable'; $info.text=''; $info | ConvertTo-Json -Depth 6 -Compress; exit 0 }
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$asAction = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and -not $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
function Await-Result($operation, [Type]$resultType) {
    $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
    if (-not $task.Wait(45000)) { throw 'WinRT operation timed out' }
    return $task.Result
}
$file = Await-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:ADVENTURE_OCR_PDF)) ([Windows.Storage.StorageFile])
$document = Await-Result ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
$pageIndex = [int]$env:ADVENTURE_OCR_PAGE - 1
if ($pageIndex -lt 0 -or $pageIndex -ge $document.PageCount) { throw 'PDF page out of bounds' }
$page = $document.GetPage($pageIndex)
$stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
$options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
$scale = [Math]::Min(300.0 / 96.0, ([Windows.Media.Ocr.OcrEngine]::MaxImageDimension - 1) / [Math]::Max($page.Size.Width, $page.Size.Height))
$options.DestinationWidth = [uint32][Math]::Floor($page.Size.Width * $scale)
$options.DestinationHeight = [uint32][Math]::Floor($page.Size.Height * $scale)
$task = $asAction.Invoke($null, @($page.RenderToStreamAsync($stream, $options)))
if (-not $task.Wait(45000)) { throw 'PDF render timed out' }
$stream.Seek(0)
$bridge = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
$imageFile = [System.IO.File]::Create($env:ADVENTURE_OCR_IMAGE)
try { $bridge.CopyTo($imageFile) } finally { $imageFile.Dispose() }
$stream.Seek(0)
$decoder = Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$transform = New-Object Windows.Graphics.Imaging.BitmapTransform
$transform.Rotation = [Windows.Graphics.Imaging.BitmapRotation]([int]$env:ADVENTURE_OCR_ROTATION / 90)
$bitmap = Await-Result ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied, $transform, [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation, [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
$ocr = Await-Result ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$lines = @($ocr.Lines | ForEach-Object { $_.Text })
$info.text = [String]::Join("`n", $lines)
$info.lines = $lines
$info.status = if ([String]::IsNullOrWhiteSpace($info.text)) { 'unresolved' } else { 'needs_review' }
$info.reason = if ([String]::IsNullOrWhiteSpace($info.text)) { 'no_text_recognized' } else { 'visual_review_required' }
$info.language = $engine.RecognizerLanguage.LanguageTag
$info.width = $bitmap.PixelWidth
$info.height = $bitmap.PixelHeight
$info.requested_dpi = 300
$info.rotation_degrees_clockwise = [int]$env:ADVENTURE_OCR_ROTATION
$info.effective_dpi = 96.0 * $scale
$bitmap.Dispose(); $stream.Dispose(); $page.Dispose()
$info | ConvertTo-Json -Depth 6 -Compress
"""


def windows_ocr(pdf: Path | None = None, page: int = 1, language: str = "en-US", image: Path | None = None,
                rotation: int = 0) -> dict:
    env = os.environ.copy()
    env.update(ADVENTURE_OCR_PROBE="1" if pdf is None else "0",
               ADVENTURE_OCR_PDF=str(pdf.resolve()) if pdf else "",
               ADVENTURE_OCR_PAGE=str(page), ADVENTURE_OCR_LANGUAGE=language,
               ADVENTURE_OCR_ROTATION=str(rotation),
               ADVENTURE_OCR_IMAGE=str(image.resolve()) if image else "")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_COMMAND],
                            env=env, capture_output=True, encoding="utf-8", timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Windows OCR command failed")
    return json.loads(result.stdout.lstrip("\ufeff"))


def targets(report: dict) -> list[tuple[dict, int]]:
    return [(doc, p["pdf_page"]) for doc in report["documents"] for p in doc["page_diagnostics"]
            if any(f in p["flags"] for f in ("ocr_review_needed_image_with_little_text", "ocr_or_pdf_repair_review_needed"))]


def run(root: Path, output: Path, report_path: Path, document_id: str | None, page: int | None,
        languages: dict, rotations: dict) -> None:
    diagnostics = json.loads((root / "data/preparation_diagnostics.json").read_text(encoding="utf-8"))
    selected = targets(diagnostics)
    if document_id is not None:
        selected = [(doc, n) for doc, n in selected if doc["document_id"] == document_id and n == page]
        if not selected:
            raise ValueError("Requested page is not an existing OCR target")
    records = []
    for doc, number in selected:
        name = f"{doc['document_id']}_p{number:03d}"
        folder = output / name
        record_path = folder / "ocr.json"
        language = languages.get(doc["document_id"], "en-US")
        rotation = rotations.get(f"{doc['document_id']}:{number}", 0)
        if rotation not in (0, 90, 180, 270):
            raise ValueError("Rotation must be 0, 90, 180, or 270 degrees")
        pdf = root / "data/raw" / doc["pdf_filename"]
        if digest(pdf.read_bytes()) != doc["pdf_sha256"]:
            raise ValueError("Original PDF hash mismatch")
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if (record["pdf_sha256"] != doc["pdf_sha256"] or record["requested_language"] != language
                    or record.get("rotation_degrees_clockwise", 0) != rotation):
                raise ValueError("OCR cache identity mismatch; use a new output directory")
            if digest((folder / "text.txt").read_bytes()) != record["ocr_text_sha256"]:
                raise ValueError("OCR cache text changed")
        else:
            folder.mkdir(parents=True, exist_ok=True)
            try:
                record = windows_ocr(pdf, number, language, folder / "page.png", rotation)
            except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
                record = {"status": "unresolved", "reason": str(exc), "text": "", "tool": "Windows.Media.Ocr"}
            text = record.pop("text")
            record.update(document_id=doc["document_id"], pdf_filename=doc["pdf_filename"],
                          pdf_sha256=doc["pdf_sha256"], pdf_page=number, requested_language=language,
                          rotation_degrees_clockwise=rotation,
                          ocr_text_sha256=digest(text.encode("utf-8")),
                          image_sha256=digest((folder / "page.png").read_bytes()) if (folder / "page.png").exists() else None,
                          confidence=None, confidence_note="Windows API exposes no word confidence here; nonempty does not mean readable.")
            save(folder / "text.txt", text.encode("utf-8"))
            save_json(record_path, record)
        records.append({"document_id": doc["document_id"], "pdf_page": number,
                        "record_path": record_path.relative_to(root).as_posix(),
                        "record_sha256": digest(record_path.read_bytes()),
                        "status": record["status"], "reason": record["reason"]})
        print(f"{name} {record['status']}: {record['reason']}", flush=True)
    save_json(report_path, {"target_count": len(records), "pages": records,
                           "counts": dict(Counter(r["status"] for r in records))})


def revise(root: Path, review_path: Path, output: Path, activate: bool = False) -> None:
    """Export only reviewed changes to a separate candidate/dataset revision."""
    review = json.loads(review_path.read_text(encoding="utf-8"))
    base_path = root / "data/manifest.jsonl"
    if digest(base_path.read_bytes()) != review["source_manifest_sha256"]:
        raise ValueError("Base manifest changed since OCR review")
    if not output.resolve().is_relative_to((root / "data/ocr_revisions").resolve()):
        raise ValueError("Output must be a separate data/ocr_revisions directory")
    rows = [json.loads(line) for line in base_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    source_rows = {row["text_id"]: dict(row) for row in rows}
    diagnostics = json.loads((root / "data/preparation_diagnostics.json").read_text(encoding="utf-8"))
    eligible = {(d["document_id"], n) for d, n in targets(diagnostics)}
    candidates = {}
    seen = set()
    changes = []
    for decision in review["pages"]:
        key = (decision["document_id"], decision["pdf_page"])
        if key not in eligible or key in seen:
            raise ValueError("Review contains a duplicate or unflagged page")
        seen.add(key)
        if decision["decision"] not in ("accepted", "partial_unresolved", "unresolved"):
            raise ValueError("Unknown review decision")
        if decision["decision"] == "unresolved":
            if decision.get("accepted_lines"):
                raise ValueError("Unresolved pages cannot contribute text")
            continue
        raw_path = root / decision["record_path"]
        if digest(raw_path.read_bytes()) != decision["record_sha256"]:
            raise ValueError("OCR record changed since review")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        if raw["document_id"] != key[0] or raw["pdf_page"] != key[1] or raw["status"] != "needs_review":
            raise ValueError("OCR record identity/status mismatch")
        raw_text = (raw_path.parent / "text.txt").read_bytes()
        if digest(raw_text) != raw["ocr_text_sha256"] or raw_text.decode("utf-8") != "\n".join(raw["lines"]):
            raise ValueError("OCR text hash or lines mismatch")
        if digest((raw_path.parent / "page.png").read_bytes()) != raw["image_sha256"]:
            raise ValueError("Reviewed OCR image changed")
        indices = decision["accepted_lines"]
        if not indices or indices != sorted(set(indices)) or any(type(i) is not int or not 1 <= i <= len(raw["lines"]) for i in indices):
            raise ValueError("Invalid accepted OCR line indices")
        text = "\n".join(raw["lines"][i - 1] for i in indices)
        if not text.strip() or text != decision["accepted_text"]:
            raise ValueError("Accepted OCR text must be an exact selection of engine lines")
        doc_id = key[0]
        if doc_id not in candidates:
            source = root / f"data/extracted/{doc_id}.json"
            candidate = json.loads(source.read_text(encoding="utf-8"))
            original = root / "data/raw" / candidate["pdf_filename"]
            if digest(original.read_bytes()) != candidate["pdf_sha256"] or raw["pdf_sha256"] != candidate["pdf_sha256"]:
                raise ValueError("Original PDF changed")
            if digest(render(candidate["pages"]).encode("utf-8")) != candidate["candidate_sha256"]:
                raise ValueError("Base candidate changed")
            candidate["parent_candidate_sha256"] = candidate["candidate_sha256"]
            candidate["extraction_method"] = "pypdf_text_layer+windows_media_ocr"
            candidate["ocr_provenance"] = []
            candidates[doc_id] = candidate
        candidate = candidates[doc_id]
        page = candidate["pages"][key[1] - 1]
        original_text = page["text"]
        # Preserve the old text layer (often just a footer), without guessing missing words.
        page["text"] = text + ("\n" + original_text if original_text.strip() else "")
        page["characters"] = len(page["text"])
        page["flags"] = sorted(set(page["flags"] + ["ocr_" + decision["decision"]]))
        page["ocr_method"] = "Windows.Media.Ocr"
        page["original_text_sha256"] = digest(original_text.encode("utf-8"))
        candidate["ocr_provenance"].append(decision | {"tool": raw["tool"], "tool_version": raw["tool_version"],
                                                       "language": raw["language"], "ocr_text_sha256": raw["ocr_text_sha256"]})
    for doc_id, candidate in candidates.items():
        path = root / "data/extracted/ocr_revisions" / output.name / f"{doc_id}.txt"
        metadata = path.with_suffix(".json")
        content = render(candidate["pages"]).encode("utf-8")
        candidate["candidate_sha256"] = digest(content)
        candidate["candidate_path"] = path.relative_to(root).as_posix()
        save(path, content)
        save_json(metadata, candidate)
        for row in rows:
            if row["document_id"] != doc_id:
                continue
            affected = [p["pdf_page"] for p in candidate["ocr_provenance"] if p["pdf_page"] in row["pdf_pages"]]
            if not affected:
                continue
            slices = row["segmentation"].get("page_slices", {})
            if any(str(n) in slices for n in affected):
                raise ValueError("OCR changed a sliced page; re-review segmentation offsets first")
            pages = select_pages(candidate, row["pdf_pages"], slices)
            content = render(pages).encode("utf-8")
            if digest(content) == row["text_sha256"]:
                continue
            text_path = output / "texts" / f"{row['text_id']}.txt"
            save(text_path, content)
            old_hash = row["text_sha256"]
            row.update(text_path=text_path.relative_to(root).as_posix(), text_sha256=digest(content),
                       parent_text_sha256=old_hash, candidate_sha256=candidate["candidate_sha256"],
                       candidate_path=candidate["candidate_path"], candidate_metadata_path=metadata.relative_to(root).as_posix(),
                       extraction_method=candidate["extraction_method"], ocr_pages=affected,
                       ocr_review_path=review_path.relative_to(root).as_posix(), ocr_review_sha256=digest(review_path.read_bytes()),
                       characters=len(content.decode("utf-8")), words=len(" ".join(p["text"] for p in pages).split()),
                       quality_flags=sorted(set(row["quality_flags"] + ["ocr_" + p["decision"] for p in candidate["ocr_provenance"] if p["pdf_page"] in affected])))
            changes.append({"text_id": row["text_id"], "parent_text_sha256": old_hash,
                            "text_sha256": row["text_sha256"], "ocr_pages": affected})
    if seen != eligible:
        raise ValueError("Every previously flagged page must have a review decision")
    manifest = output / "manifest.jsonl"
    save(manifest, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8"))
    errors = validate(root, manifest_path=manifest)
    if errors:
        raise ValueError("; ".join(errors))
    save_json(output / "dataset.json", {"manifest_path": manifest.relative_to(root).as_posix(),
                                       "manifest_sha256": digest(manifest.read_bytes()),
                                       "source_manifest_sha256": review["source_manifest_sha256"],
                                       "status": "prepared_not_evaluation_frozen", "changed_inputs": changes,
                                       "changed_candidates": sorted(candidates),
                                       "unresolved_pages": [{"document_id": p["document_id"], "pdf_page": p["pdf_page"], "reason": p["reason"]}
                                                            for p in review["pages"] if p["decision"] != "accepted"],
                                       "input_contract": "Both adapters must use the same locked dataset snapshot and exact text bytes; no provider-specific OCR/preprocessing."})
    if activate:
        save(root / "data/active_dataset.json", (output / "dataset.json").read_bytes())
    assert all(row == source_rows[row["text_id"]] for row in rows if row["text_id"] not in {c["text_id"] for c in changes})
    print(f"Revision valid: changed candidates={len(candidates)}, changed texts={len(changes)}; base inputs untouched")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("probe")
    revision = sub.add_parser("revise")
    revision.add_argument("--review", type=Path, default=ROOT / "data/ocr_review.json")
    revision.add_argument("--output", type=Path, default=ROOT / "data/ocr_revisions/windows-v1")
    revision.add_argument("--activate", action="store_true", help="Create an immutable shared dataset pointer; never overwrite a different existing pointer")
    execution = sub.add_parser("run")
    execution.add_argument("--document")
    execution.add_argument("--page", type=int)
    execution.add_argument("--output", type=Path, default=ROOT / "data/ocr/windows-v2")
    execution.add_argument("--report", type=Path, required=True)
    execution.add_argument("--languages", type=Path, default=ROOT / "data/ocr_languages.json")
    execution.add_argument("--rotations", type=Path, default=ROOT / "data/ocr_rotations.json")
    args = parser.parse_args()
    try:
        if args.command == "probe":
            print(json.dumps(windows_ocr(), ensure_ascii=False, indent=2))
        elif args.command == "revise":
            revise(ROOT, args.review.resolve(), args.output.resolve(), args.activate)
        else:
            if (args.document is None) != (args.page is None):
                raise ValueError("--document and --page must be provided together")
            languages = json.loads(args.languages.read_text(encoding="utf-8"))
            rotations = json.loads(args.rotations.read_text(encoding="utf-8"))
            run(ROOT, args.output.resolve(), args.report, args.document, args.page, languages, rotations)
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
