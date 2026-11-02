"""Sequential HW1 CLI. Default matrix: 30 texts x 2 models x 2 prompts x 2 sampling."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import sys
import uuid

from dotenv import load_dotenv
from pydantic import ValidationError

from scripts.validate_golden import contracts, validate as golden_gate
from src.budget import Budget, NANO, history_events, units
from src.dataset import load_snapshot
from src.ollama import OllamaConfig, OllamaProvider
from src.pipeline import ExperimentConfig, Pipeline, file_hash, fingerprint, write_once
from src.providers import OpenAIProvider, Sampling
from src.schema import card_json_schema

ROOT = Path(__file__).resolve().parent


def within(root: Path, path: str) -> Path:
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Configuration path escapes repository")
    return resolved


def frozen_inputs(root, cfg):
    frozen = json.loads(within(root, cfg.evaluation_snapshot).read_text(encoding="utf-8"))
    for key, current in contracts(root).items():
        if frozen[key] != current:
            raise ValueError(f"Frozen evaluation contract changed: {key}")
    for path_key, hash_key in (("schema_source_path", "schema_source_sha256"),
                               ("schema_export_path", "schema_export_sha256"),
                               ("annotation_status_path", "annotation_status_sha256")):
        if file_hash(within(root, frozen[path_key])) != frozen[hash_key]:
            raise ValueError(f"Frozen artifact changed: {path_key}")
    items = load_snapshot(root, within(root, cfg.dataset_descriptor))
    expected = {r["text_id"]: r for r in frozen["inputs"]}
    if len(items) != 30 or len(expected) != 30:
        raise ValueError("Full dataset must contain 30 frozen texts")
    for item in items:
        if item.text_id not in expected or item.text_sha256 != expected[item.text_id]["text_sha256"] or item.split != expected[item.text_id]["split"]:
            raise ValueError("Active dataset differs from frozen evaluation inputs")
    for row in frozen["annotations"]:
        if file_hash(within(root, row["annotation_path"])) != row["annotation_sha256"]:
            raise ValueError("Frozen manual annotation changed: " + row["text_id"])
    gate = golden_gate(root)
    if not gate["complete"]:
        raise ValueError("Golden completion gate failed; run scripts/validate_golden.py validate")
    return items, frozen


def code_identity(root):
    paths = ["main.py", "src/pipeline.py", "src/budget.py", "src/providers.py", "src/ollama.py", "src/schema.py", "src/dataset.py", "uv.lock"]
    return {path: file_hash(root / path) for path in paths}


def run(args, root=ROOT) -> int:
    load_dotenv(root / ".env", override=False)
    cfg = ExperimentConfig.model_validate_json(within(root, args.config).read_text(encoding="utf-8"))
    items, frozen = frozen_inputs(root, cfg)
    providers = list(cfg.models) if args.provider == "all" else [args.provider]
    prompt_names = list(cfg.prompts) if args.prompt == "all" else [args.prompt]
    samplings = list(cfg.sampling) if args.sampling == "all" else [args.sampling]
    if args.text:
        wanted = set(args.text)
        if not wanted <= {i.text_id for i in items}:
            raise ValueError("Unknown text selector")
        items = tuple(i for i in items if i.text_id in wanted)
    models = {"openai": os.getenv("PROVIDER_MODEL") or cfg.models["openai"],
              "ollama": os.getenv("LOCAL_MODEL") or cfg.models["ollama"]}
    errors = []
    for name in prompt_names:
        if not within(root, cfg.prompts[name]).is_file():
            errors.append(f"Missing required prompt {name}: {cfg.prompts[name]}; requested matrix was not reduced")
    if not within(root, cfg.repair_prompt).is_file():
        errors.append("Missing fixed repair prompt: " + cfg.repair_prompt)
    if "openai" in providers and models["openai"] not in cfg.pricing["model_ids"]:
        errors.append("Configured external model has no verified compatible pricing profile; no fallback")
    if "openai" in providers and cfg.operations.max_output_tokens > 16384:
        errors.append("Configured output limit exceeds selected provider model limit")
    if os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") != "https://api.openai.com/v1":
        errors.append("Custom OpenAI endpoint requires explicit pricing/accounting review")
    events = history_events(root / "results", cfg.pricing)
    ledger_path = within(root, cfg.budget["ledger_path"])
    if not ledger_path.is_relative_to((root / "results").resolve()):
        errors.append("Budget ledger must remain under results/")
    ledger_total = 0
    if ledger_path.exists():
        with sqlite3.connect(ledger_path.as_uri() + "?mode=ro", uri=True) as db:
            ledger_total = db.execute("SELECT COALESCE(SUM(accounted),0) FROM charges").fetchone()[0]
    declared = units(cfg.budget["prior_spend_usd"])
    manual_id = "manual_" + str(cfg.budget["prior_spend_reference"])
    historical_total = sum(e["amount"] for e in events if e["id"] != manual_id) + declared
    if max(ledger_total, historical_total) > units(cfg.budget["limit_usd"]):
        errors.append("Cumulative historical spend/reservations exceed configured homework budget")
    plan = {"mode": "dry_run" if args.dry_run else "preflight", "text_count": len(items),
            "providers": providers, "prompts": prompt_names, "sampling": samplings,
            "planned_initial_executions": len(items) * len(providers) * len(prompt_names) * len(samplings),
            "max_attempts_per_execution": cfg.operations.max_call_attempts,
            "historical_external_call_records": len(events), "existing_ledger_accounted_usd": ledger_total / NANO,
            "model_generation_calls": 0, "errors": errors,
            "network_readiness": "not_checked_in_dry_run" if args.dry_run else "pending"}
    if args.dry_run or errors:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 2 if errors else 0
    if "openai" in providers and not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Missing OPENAI_API_KEY; no model calls made")
    adapters, runtime = {}, {}
    budget = None
    lock_handle = None
    run_lock = None
    try:
        if "ollama" in providers:
            local_config = OllamaConfig(model=models["ollama"], base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
                context_size=cfg.operations.local_context_size, timeout_s=cfg.operations.local_timeout_s,
                sampling=Sampling(**cfg.sampling[samplings[0]], max_output_tokens=cfg.operations.max_output_tokens))
            adapters["ollama"] = OllamaProvider(local_config)
            probe = adapters["ollama"].runtime()
            if not probe["ready"]:
                raise ValueError("Ollama prerequisite failed: " + str(probe["blocker"]) + "; no external generation was started")
            runtime["ollama"] = {"version": probe["version"], "model": probe["model"], "model_info": probe["show"].get("model_info"),
                                 "base_url": local_config.base_url, "context_size": local_config.context_size}
        if "openai" in providers:
            # Constructor only. Availability/authentication errors stop on first request.
            from openai import OpenAI
            adapters["openai"] = OpenAIProvider(models["openai"], client=OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0))
        environment = {"python": platform.python_version(), "platform": platform.platform(), "processor": platform.processor(),
                       "packages": {p: importlib.metadata.version(p) for p in ("openai", "httpx", "httpx2", "pydantic")}}
        protocol = {"protocol_version": "hw1-pipeline-v1", "config": cfg.model_dump(mode="json"), "models": models,
                    "runtime": runtime, "environment": environment, "code": code_identity(root),
                    "evaluation_snapshot_sha256": file_hash(within(root, cfg.evaluation_snapshot)),
                    "dataset_descriptor_sha256": file_hash(within(root, cfg.dataset_descriptor)),
                    "repair_prompt_sha256": file_hash(within(root, cfg.repair_prompt)), "schema_sha256": fingerprint(card_json_schema())}
        jobs = []
        for provider in providers:
            for prompt in prompt_names:
                for sampling_name in samplings:
                    for item in items:
                        identity = {"protocol": protocol, "provider": provider, "model": models[provider], "text_id": item.text_id,
                                    "input_sha256": item.text_sha256, "split": item.split, "prompt_version": prompt,
                                    "prompt_sha256": file_hash(within(root, cfg.prompts[prompt])), "sampling_name": sampling_name,
                                    "sampling": asdict(Sampling(**cfg.sampling[sampling_name], max_output_tokens=cfg.operations.max_output_tokens))}
                        jobs.append((fingerprint(identity), identity, item))
        run_identity = fingerprint([key for key, _, _ in jobs])
        run_id = args.resume or args.run_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:12])
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
            raise ValueError("Unsafe run ID")
        run_dir = root / "results/runs" / run_id
        if args.resume:
            header = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            if header["run_identity_sha256"] != run_identity:
                raise ValueError("Resume refused: full experiment identity/selection/runtime differs")
        else:
            run_dir.mkdir(parents=True, exist_ok=False)
        run_lock = run_dir / "active.lock"
        lock_handle = run_lock.open("x")
        lock_handle.write(str(os.getpid()))
        lock_handle.flush()
        for key, _, _ in jobs:
            directory = run_dir / "jobs" / key
            if directory.exists() and any(directory.iterdir()) and not (directory / "result.json").exists():
                raise ValueError("Resume contains unknown partial/in-flight attempt; reconcile evidence before continuing")
            if (directory / "result.json").exists():
                checksum = directory / "result.sha256"
                if not checksum.exists() or checksum.read_text().strip() != file_hash(directory / "result.json"):
                    raise ValueError("Resume contains changed/incomplete terminal result")
        if not args.resume:
            write_once(run_dir / "run.json", {"run_id": run_id, "run_identity_sha256": run_identity,
                       "protocol": protocol, "jobs": [{"job_id": key, "identity": identity} for key, identity, _ in jobs]})
        budget = Budget(ledger_path, cfg.budget["limit_usd"])
        manual_id = "manual_" + str(cfg.budget["prior_spend_reference"])
        write_once(root / "results/budget_adjustments" / (fingerprint(cfg.budget["prior_spend_reference"]) + ".json"),
                   {"kind": "manual_budget_adjustment", "reference": cfg.budget["prior_spend_reference"],
                    "usd": cfg.budget["prior_spend_usd"]})
        budget.import_charge(manual_id, declared, True)
        for event in events:
            budget.import_charge(event["id"], event["amount"], event["known"])
        if budget.total() > budget.limit:
            raise ValueError("Cumulative budget exhausted after historical reconciliation")
        outcomes = []
        for key, identity, item in jobs:
            reused = (run_dir / "jobs" / key / "result.json").exists()
            result = Pipeline(adapters[identity["provider"]], identity["provider"], cfg.operations, cfg.pricing, budget).extract(
                item.content, within(root, cfg.prompts[identity["prompt_version"]]).read_text(encoding="utf-8"),
                within(root, cfg.repair_prompt).read_text(encoding="utf-8"), card_json_schema(),
                Sampling(**cfg.sampling[identity["sampling_name"]], max_output_tokens=cfg.operations.max_output_tokens),
                identity, run_dir / "jobs" / key)
            outcomes.append({"job_id": key, "reused": reused, "status": result["status"], "first_pass_valid": result["first_pass_valid"],
                             "final_valid": result["final_valid"], "stop_batch_reason": result["stop_batch_reason"]})
            print(f"{run_id}: {len(outcomes)}/{len(jobs)} {item.text_id} {result['status']}")
            if result["stop_batch_reason"]:
                break
        stopped = bool(outcomes and outcomes[-1]["stop_batch_reason"])
        write_once(run_dir / ("summary_" + uuid.uuid4().hex + ".json"), {"run_id": run_id, "planned": len(jobs),
                   "record_count": len(outcomes), "stopped": stopped, "outcomes": outcomes,
                   "cumulative_accounted_usd": budget.total() / NANO})
        return 2 if stopped or any(o["status"] != "succeeded" for o in outcomes) else 0
    finally:
        for adapter in adapters.values():
            adapter.close()
        if budget:
            budget.close()
        if lock_handle:
            lock_handle.close()
            run_lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--provider", choices=("all", "openai", "ollama"), default="all")
    parser.add_argument("--prompt", choices=("all", "v1", "v2"), default="all")
    parser.add_argument("--sampling", choices=("all", "A", "B"), default="all")
    parser.add_argument("--text", action="append", help="Exact text ID; repeat to select several. Default: all 30")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run-id")
    group.add_argument("--resume", metavar="RUN_ID")
    try:
        return run(parser.parse_args())
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print("Preflight/execution stopped: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
