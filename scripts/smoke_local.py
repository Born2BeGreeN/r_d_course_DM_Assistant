"""One local-only development-page smoke, or an honest prerequisite report."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib.metadata
import os
from pathlib import Path
import platform
import re
import shutil
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from scripts.prepare_data import ROOT, digest, save_json
from src.dataset import load_snapshot
from src.ollama import OllamaConfig, OllamaProvider
from src.providers import ProviderError
from src.schema import AdventureCard, card_json_schema


def smoke(root: Path) -> dict:
    config = OllamaConfig.from_env(root / ".env")
    cli = shutil.which("ollama")
    if not cli:
        for path in (Path(os.getenv("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe",
                     Path("C:/Program Files/Ollama/ollama.exe")):
            if path.is_file():
                cli = str(path)
                break
    report = {"kind": "local_smoke_not_benchmark", "status": "blocked", "smoke_attempted": False,
              "generation_calls": 0, "external_provider_calls": 0,
              "configuration": asdict(config), "cli_path": cli,
              "host": {"platform": platform.platform(), "processor": platform.processor(),
                       "python": platform.python_version(), "httpx": importlib.metadata.version("httpx"),
                       "gpu": None, "gpu_note": "Not measured; do not infer GPU usage."},
              "model_response": None, "schema_valid": None}
    provider = OllamaProvider(config)
    try:
        runtime = provider.runtime()
        report["runtime_before"] = runtime
        if not runtime["ready"]:
            report["blocker"] = runtime["blocker"]
            return report
        text = next(item for item in load_snapshot(root) if item.split == "development")
        markers = list(re.finditer(r"\[PDF_PAGE=(\d+)\]", text.content))
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(text.content)
            excerpt = text.content[marker.start():end]
            if len(excerpt[marker.end() - marker.start():].strip()) >= 200:
                break
        else:
            report["blocker"] = "no_usable_development_page"
            return report
        prompt_path = root / "prompts/v1.txt"
        prompt = prompt_path.read_text(encoding="utf-8")
        schema_path = root / "docs/adventure_card.schema.json"
        import json
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if schema != card_json_schema():
            raise ValueError("Exported schema is stale")
        report["input"] = {"text_id": text.text_id, "split": "development", "parent_text_sha256": text.text_sha256,
                           "scope": "First complete nonempty PDF page of development input; smoke excerpt only, not a benchmark corpus input.",
                           "pdf_page": int(marker.group(1)), "character_start": marker.start(), "character_end": end,
                           "text_sha256": digest(excerpt.encode("utf-8")), "text": excerpt}
        report.update(prompt_path="prompts/v1.txt", prompt_sha256=digest(prompt_path.read_bytes()),
                      schema_sha256=digest(schema_path.read_bytes()), smoke_attempted=True, generation_calls=1)
        try:
            result = provider.generate(excerpt, prompt, schema, config.sampling, config.timeout_s)
            report["model_response"] = asdict(result)
            try:
                AdventureCard.model_validate_json(result.raw_text)
                report.update(schema_valid=True, status="passed")
            except ValidationError as exc:
                report.update(schema_valid=False, status="failed", blocker="smoke_schema_validation_failed",
                              schema_errors=[{"field": list(e["loc"]), "type": e["type"]} for e in exc.errors()])
        except ProviderError as exc:
            report.update(model_response=asdict(exc.response), status="failed", blocker=exc.response.error["type"])
        report["runtime_after"] = provider.runtime()
        loaded = (report["runtime_after"].get("running_models") or {}).get("models", [])
        actual = next((m for m in loaded if m.get("name") == config.model or m.get("model") == config.model), None)
        report["loaded_model_after"] = actual
        if actual and type(actual.get("context_length")) is int and actual["context_length"] < config.context_size:
            report.update(status="failed", blocker="loaded_context_smaller_than_requested")
        return report
    finally:
        provider.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = smoke(ROOT)
        save_json(args.report, report)
        print(f"Local smoke: {report['status']}; generation_calls={report['generation_calls']}; "
              f"external_provider_calls=0; blocker={report.get('blocker')}")
        return 0 if report["status"] == "passed" else 2
    except (OSError, ValueError, StopIteration) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
