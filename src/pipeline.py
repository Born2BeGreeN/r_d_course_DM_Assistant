"""Sequential extraction, bounded transport retries, one repair, durable evidence."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.budget import Budget, BudgetExceeded, NANO, reservation
from src.providers import ModelResponse, Provider, ProviderError, Sampling
from src.schema import AdventureCard


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path: Path, value) -> None:
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Refusing to overwrite historical result: {path}")
        return
    import os
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


class Operations(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    provider_timeout_s: float = Field(default=60, gt=0)
    local_timeout_s: float = Field(default=180, gt=0)
    provider_request_deadline_s: float = Field(default=150, gt=0)
    local_request_deadline_s: float = Field(default=390, gt=0)
    transport_retries: int = Field(default=1, ge=0, le=1, strict=True)
    schema_repairs: int = Field(default=1, ge=0, le=1, strict=True)
    max_call_attempts: int = Field(default=4, ge=1, le=4, strict=True)
    retry_delay_s: float = Field(default=1, ge=0)
    max_retry_after_s: float = Field(default=30, ge=0)
    max_output_tokens: int = Field(default=2048, gt=0, strict=True)
    local_context_size: int = Field(default=8192, gt=0, strict=True)

    @model_validator(mode="after")
    def budgets(self):
        if self.local_context_size <= self.max_output_tokens:
            raise ValueError("Local context must exceed output token budget")
        return self


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation_snapshot: str
    dataset_descriptor: str
    prompts: dict[str, str]
    repair_prompt: str
    sampling: dict[str, dict[str, float]]
    models: dict[str, str]
    operations: Operations
    budget: dict
    pricing: dict

    @model_validator(mode="after")
    def required_matrix(self):
        if set(self.models) != {"openai", "ollama"} or set(self.prompts) != {"v1", "v2"} or set(self.sampling) != {"A", "B"}:
            raise ValueError("Config must declare both providers, v1/v2 and A/B; use selectors for partial runs")
        for sampling in self.sampling.values():
            Sampling(**sampling, max_output_tokens=self.operations.max_output_tokens)
        if not 0 < float(self.budget["limit_usd"]) <= 5:
            raise ValueError("Homework budget cannot exceed USD 5")
        if self.pricing["currency"] != "USD" or self.pricing["billing"] != "standard_text_per_1m_tokens":
            raise ValueError("Unsupported pricing categories")
        for key in ("uncached_input_per_1m", "cached_input_per_1m", "output_per_1m"):
            from src.budget import units
            if units(self.pricing[key]) <= 0:
                raise ValueError("Verified selected-model rates must be positive")
        if self.pricing["cached_input_per_1m"] > self.pricing["uncached_input_per_1m"]:
            raise ValueError("Invalid cache discount")
        if self.pricing["reservation_input_tokens"] < 128000 or not self.pricing["reasoning_tokens_included_in_output"]:
            raise ValueError("Selected-model reservation/billing policy changed; review pricing implementation")
        return self


def retry_after_seconds(value, *, now: Callable = time.time) -> float | None:
    if value is None:
        return None
    try:
        delay = float(value)
        import math
        return max(0., delay) if math.isfinite(delay) else None
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(str(value))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0., date.timestamp() - now())
        except (ValueError, TypeError, OverflowError):
            return None


def transient(response: ModelResponse) -> bool:
    error = response.error or {}
    return error.get("http_status") in (408, 409, 429, 500, 502, 503, 504) or error.get("type") in (
        "APITimeoutError", "APIConnectionError", "local_timeout", "local_transport_error", "service_unavailable")


def fatal(response: ModelResponse) -> bool:
    error = response.error or {}
    return response.metadata.get("api_error_code") in ("invalid_api_key", "insufficient_quota", "model_not_found", "unsupported_parameter", "invalid_value") or error.get("http_status") in (400, 401, 402, 403, 404, 422) or error.get("type") in (
        "unsupported_model_sampling", "invalid_model_identifier", "configured_model_missing",
        "unsupported_parameter_or_format", "context_configuration_not_applied", "returned_model_mismatch")


def card_validation(text: str) -> tuple[dict | None, list[dict]]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON property: " + key)
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=unique)
        return AdventureCard.model_validate(value).model_dump(mode="json"), []
    except ValidationError as exc:
        return None, exc.errors(include_url=False, include_input=False, include_context=False)
    except (ValueError, TypeError) as exc:
        return None, [{"type": "invalid_json", "loc": [], "msg": str(exc)}]


class Pipeline:
    def __init__(self, provider: Provider, provider_name: str, operations: Operations, pricing: dict,
                 budget: Budget | None, *, clock=time.monotonic, sleep=time.sleep):
        self.provider = provider
        self.name = provider_name
        self.ops = operations
        self.pricing = pricing
        self.budget = budget
        self.clock = clock
        self.sleep = sleep

    def extract(self, text: str, prompt: str, repair_prompt: str, schema: dict, sampling: Sampling,
                identity: dict, output: Path) -> dict:
        identity = dict(identity) | {"request_contract": {
            "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "repair_prompt_sha256": hashlib.sha256(repair_prompt.encode("utf-8")).hexdigest(),
            "schema_sha256": fingerprint(schema), "sampling": asdict(sampling),
            "operations": self.ops.model_dump(mode="json"), "provider": self.name}}
        identity_hash = fingerprint(identity)
        result_path = output / "result.json"
        if result_path.exists():
            if not (output / "result.sha256").exists() or (output / "result.sha256").read_text().strip() != file_hash(result_path):
                raise ValueError("Resume refused: terminal result hash mismatch or missing checksum")
            saved = json.loads(result_path.read_text(encoding="utf-8"))
            if saved.get("identity") != identity or saved.get("identity_sha256") != identity_hash:
                raise ValueError("Resume refused: experiment identity mismatch")
            for attempt in saved["attempts"]:
                if file_hash(output / attempt["intent_path"]) != attempt["intent_sha256"]:
                    raise ValueError("Resume refused: saved intent changed")
                if attempt.get("response_path") and file_hash(output / attempt["response_path"]) != attempt["response_sha256"]:
                    raise ValueError("Resume refused: saved attempt changed")
                if attempt.get("validation_path") and file_hash(output / attempt["validation_path"]) != attempt["validation_sha256"]:
                    raise ValueError("Resume refused: saved validation changed")
            return saved
        if output.exists() and any(output.iterdir()):
            raise ValueError("Partial/in-flight job requires manual reconciliation; do not repeat unknown calls")
        output.mkdir(parents=True, exist_ok=True)
        started = self.clock()
        result = {"kind": "extraction_result", "identity": identity, "identity_sha256": identity_hash,
                  "status": "failed", "attempts": [], "actual_call_attempts": 0,
                  "first_pass_valid": False, "final_valid": False, "transport_retry_count": 0,
                  "repair_count": 0, "final_card": None, "failure": None, "stop_batch_reason": None}
        timeout = self.ops.provider_timeout_s if self.name == "openai" else self.ops.local_timeout_s
        deadline_s = self.ops.provider_request_deadline_s if self.name == "openai" else self.ops.local_request_deadline_s
        unknown_costs, known_cost, accounted_cost = 0, 0., 0.
        usage_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_input_tokens": 0, "reasoning_tokens": 0}
        unknown_usage = set()
        invalid_answer, validation_errors = "", []
        for stage_index in range(1 + self.ops.schema_repairs):
            stage = "generation" if stage_index == 0 else "repair"
            request_text = text if stage_index == 0 else json.dumps({"source_text": text, "invalid_answer": invalid_answer,
                                                        "validation_errors": validation_errors}, ensure_ascii=False)
            request_prompt = prompt if stage_index == 0 else repair_prompt
            deadline = self.clock() + deadline_s
            response = None
            stage_failure = False
            for retry in range(1 + self.ops.transport_retries):
                remaining = deadline - self.clock()
                if remaining <= 0 or result["actual_call_attempts"] >= self.ops.max_call_attempts:
                    result["failure"] = "request_deadline_or_attempt_limit"
                    stage_failure = True
                    break
                number = len(result["attempts"]) + 1
                charge_id = None
                reserved = reservation(self.pricing, sampling.max_output_tokens) if self.name == "openai" else 0
                try:
                    if self.name == "openai":
                        if self.budget is None:
                            raise ValueError("External requests require the cumulative budget ledger")
                        charge_id = self.budget.reserve(reserved, identity_hash)
                except BudgetExceeded:
                    result.update(failure="budget_exhausted", stop_batch_reason="budget_exhausted")
                    stage_failure = True
                    break
                prefix = f"attempt_{number:02d}"
                write_once(output / f"{prefix}.intent.json", {"kind": "call_intent", "provider": self.name,
                    "budget_charge_id": charge_id, "reservation_units": reserved, "identity_sha256": identity_hash,
                    "stage": stage, "retry_index": retry, "request_text_sha256": hashlib.sha256(request_text.encode()).hexdigest(),
                    "prompt_sha256": hashlib.sha256(request_prompt.encode()).hexdigest(),
                    "schema_sha256": fingerprint(schema), "timeout_s": min(timeout, remaining),
                    "pricing": self.pricing if self.name == "openai" else None,
                    "repair_envelope": json.loads(request_text) if stage_index else None})
                try:
                    response = self.provider.generate(request_text, request_prompt, schema, sampling, min(timeout, remaining))
                except ProviderError as exc:
                    response = exc.response
                except Exception:
                    # The reserved intent is durable; unknown in-flight spend must
                    # not disappear or trigger an automatic duplicate request.
                    result.update(failure="unexpected_adapter_error", stop_batch_reason="unexpected_adapter_error")
                    stage_failure = True
                    result["actual_call_attempts"] += 1
                    unknown_usage.update(usage_totals)
                    result["attempts"].append({"number": number, "stage": stage, "retry_index": retry,
                        "response_path": None, "response_sha256": None, "intent_path": f"{prefix}.intent.json",
                        "intent_sha256": file_hash(output / f"{prefix}.intent.json"),
                        "budget_charge_id": charge_id, "outcome": "unknown_after_adapter_error"})
                    if charge_id:
                        unknown_costs += 1
                        accounted_cost += reserved / NANO
                    break
                # Persist response/usage BEFORE schema parsing or budget settlement.
                path = output / f"{prefix}.response.json"
                write_once(path, {"kind": "raw_attempt", "budget_charge_id": charge_id, "stage": stage,
                                  "retry_index": retry, "response": asdict(response),
                                  "pricing": self.pricing if self.name == "openai" else None})
                calls = response.metadata.get("sdk_call_count", response.metadata.get("http_attempts", 1))
                if calls not in (0, 1) or response.metadata.get("sdk_retries", response.metadata.get("http_retries", 0)) != 0:
                    result["stop_batch_reason"] = "hidden_adapter_retries"
                result["actual_call_attempts"] += calls if calls in (0, 1) else 1
                if retry and calls:
                    result["transport_retry_count"] += 1
                if stage_index and calls and result["repair_count"] == 0:
                    result["repair_count"] = 1
                cost = {"estimated_usd": 0., "accounted_usd": 0., "usage_known": True}
                if charge_id:
                    allowed_model = response.returned_model is None or response.returned_model in self.pricing["model_ids"]
                    cost = self.budget.settle(charge_id, asdict(response.usage) if allowed_model else None,
                                              self.pricing, no_call=calls == 0)
                    if not allowed_model or self.budget.total() > self.budget.limit:
                        result["stop_batch_reason"] = "pricing_model_or_budget_overage"
                known_cost += cost["estimated_usd"] or 0.
                accounted_cost += cost["accounted_usd"]
                unknown_costs += int(not cost["usage_known"])
                for key in usage_totals:
                    value = getattr(response.usage, key)
                    if value is None:
                        unknown_usage.add(key)
                    else:
                        usage_totals[key] += value
                result["attempts"].append({"number": number, "stage": stage, "retry_index": retry,
                    "intent_path": f"{prefix}.intent.json", "intent_sha256": file_hash(output / f"{prefix}.intent.json"),
                    "response_path": path.name, "response_sha256": file_hash(path), "budget_charge_id": charge_id, "cost": cost})
                if result["stop_batch_reason"]:
                    stage_failure = True
                    result["failure"] = result["stop_batch_reason"]
                    break
                if response.error:
                    if fatal(response):
                        result.update(failure=response.error["type"], stop_batch_reason=response.error["type"])
                        stage_failure = True
                        break
                    if transient(response) and retry < self.ops.transport_retries:
                        delay = retry_after_seconds(response.metadata.get("retry_after"))
                        delay = self.ops.retry_delay_s if delay is None else delay
                        if delay > self.ops.max_retry_after_s or delay >= deadline - self.clock():
                            result["failure"] = "retry_after_exceeds_deadline_or_bound"
                            stage_failure = True
                            break
                        self.sleep(delay)
                        continue
                    result["failure"] = response.error["type"]
                    stage_failure = True
                break
            if stage_failure or response is None:
                break
            if response.finish_status not in ("completed", "stop") or response.metadata.get("refusals") or response.metadata.get("provider_error"):
                result["failure"] = "non_success_finish_or_refusal"
                break
            card, validation_errors = card_validation(response.raw_text)
            write_once(output / f"attempt_{len(result['attempts']):02d}.validation.json",
                       {"schema_valid": card is not None, "validation_errors": validation_errors})
            result["attempts"][-1].update(validation_path=f"attempt_{len(result['attempts']):02d}.validation.json",
                validation_sha256=file_hash(output / f"attempt_{len(result['attempts']):02d}.validation.json"))
            if stage_index == 0:
                result["first_pass_valid"] = card is not None
            if card is not None:
                result.update(status="succeeded", final_valid=True, final_card=card, failure=None)
                break
            result["failure"] = "schema_invalid"
            invalid_answer = response.raw_text
        result["document_latency_s"] = self.clock() - started
        result["usage"] = {key: None if key in unknown_usage else value for key, value in usage_totals.items()}
        result["reported_usage_subtotals"] = usage_totals
        result["cost"] = {"estimated_usd": None if unknown_costs else known_cost, "known_usage_estimate_usd": known_cost,
                          "unknown_usage_attempts": unknown_costs, "conservative_accounted_usd": accounted_cost,
                          "local_energy_cost_unknown": self.name == "ollama"}
        write_once(result_path, result)
        with (output / "result.sha256").open("x", encoding="ascii") as handle:
            handle.write(file_hash(result_path) + "\n")
        return result
