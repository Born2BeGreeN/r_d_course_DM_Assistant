"""Single-attempt provider transport; validation/repair/retries belong to pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import os
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Protocol

from dotenv import load_dotenv
from openai import APIError, OpenAI


@dataclass(frozen=True)
class Sampling:
    temperature: float
    top_p: float
    max_output_tokens: int = 2048

    def __post_init__(self):
        for name, value, lower, upper in (("temperature", self.temperature, 0, 2), ("top_p", self.top_p, 0, 1)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError(f"Invalid {name}")
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer")


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    raw: dict | None = None


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    requested_model: str
    returned_model: str | None
    raw_text: str
    finish_status: str | None
    usage: TokenUsage
    started_at_utc: str
    duration_s: float
    response_id: str | None = None
    request_id: str | None = None
    raw_response: dict | None = None
    error: dict | None = None
    metadata: dict = field(default_factory=dict)


class Provider(Protocol):
    def generate(self, text: str, prompt: str, schema: dict,
                 sampling: Sampling | Mapping[str, Any], timeout_s: float) -> ModelResponse: ...


class ProviderError(RuntimeError):
    """Pipeline can inspect the failed attempt without logging SDK bodies/secrets."""

    def __init__(self, response: ModelResponse):
        self.response = response
        error = response.error or {}
        super().__init__(f"{response.provider}: {error.get('type', 'provider_error')} "
                         f"(HTTP {error.get('http_status', 'n/a')})")


class OpenAIProvider:
    def __init__(self, model: str, *, client: OpenAI):
        if not model or not model.strip():
            raise ValueError("PROVIDER_MODEL must be explicitly configured")
        self.model = model  # Preserve the exact configured ID. Never lowercase/substitute it.
        self._client = client

    @classmethod
    def from_env(cls, env_path: Path | None = Path(".env")) -> OpenAIProvider:
        if env_path is not None:
            load_dotenv(env_path, override=False)
        key = os.environ.get("OPENAI_API_KEY")
        model = os.environ.get("PROVIDER_MODEL")
        if not key or not key.strip():
            raise ValueError("OPENAI_API_KEY is required")
        if not model or not model.strip():
            raise ValueError("PROVIDER_MODEL must be explicitly configured")
        return cls(model, client=OpenAI(api_key=key, max_retries=0))

    def close(self) -> None:
        self._client.close()

    def generate(self, text: str, prompt: str, schema: dict,
                 sampling: Sampling | Mapping[str, Any], timeout_s: float) -> ModelResponse:
        if not isinstance(sampling, Sampling):
            sampling = Sampling(**sampling)
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be a positive finite number")
        started_at = datetime.now(timezone.utc).isoformat()
        start = perf_counter()
        reasoning = {"effort": "none"} if self.model.lower().startswith(("gpt-5", "gpt-6")) else None
        metadata = {"sdk_retries": 0, "sdk_call_count": 0, "reasoning_effort": "none" if reasoning else None,
                    "temperature": sampling.temperature, "top_p": sampling.top_p,
                    "max_output_tokens": sampling.max_output_tokens, "timeout_s": timeout_s}

        def failed(error: dict, request_id: str | None = None) -> ProviderError:
            return ProviderError(ModelResponse("openai", self.model, None, "", "error", TokenUsage(),
                                               started_at, perf_counter() - start, request_id=request_id,
                                               error=error, metadata=dict(metadata)))

        # Official 2026-10-31 compatibility: Sol requires reasoning, while these
        # sampling controls require reasoning=none. Do not drop controls or switch models.
        if self.model.lower() == "gpt-6.1-sol" or self.model.lower().startswith("gpt-6.1-sol-"):
            raise failed({"type": "unsupported_model_sampling", "code": "sampling_requires_reasoning_none",
                          "detail": "GPT-6.1 Sol cannot combine required temperature/top_p with supported reasoning settings. "
                                    "Set an explicitly agreed sampling-compatible API model ID before live use; no fallback was applied."})
        if self.model != self.model.strip() or self.model != self.model.lower():
            raise failed({"type": "invalid_model_identifier", "code": "exact_api_model_id_required"})
        metadata["sdk_call_count"] = 1
        try:
            # with_options also overrides retries on injected/test clients. Responses
            # create (not parse) preserves invalid JSON for shared pipeline validation.
            response = self._client.with_options(max_retries=0, timeout=float(timeout_s)).responses.create(
                model=self.model,
                instructions=prompt,
                input=[{"role": "user", "content": [{"type": "input_text", "text": text}]}],
                text={"format": {"type": "json_schema", "name": "adventure_card", "strict": True, "schema": schema}},
                temperature=sampling.temperature, top_p=sampling.top_p,
                **({"reasoning": reasoning} if reasoning else {}), max_output_tokens=sampling.max_output_tokens,
                tools=[], store=False, stream=False,
            )
        except APIError as exc:
            response_headers = getattr(getattr(exc, "response", None), "headers", {})
            metadata["retry_after"] = response_headers.get("retry-after")
            code = getattr(exc, "code", None)
            if code in ("invalid_api_key", "insufficient_quota", "model_not_found", "unsupported_parameter", "invalid_value"):
                metadata["api_error_code"] = code
            # Do not stringify SDK exceptions or persist response bodies/headers:
            # those can contain credentials or source data. Unknown usage stays None.
            raise failed({"type": type(exc).__name__, "http_status": getattr(exc, "status_code", None)},
                         getattr(exc, "request_id", None)) from None
        raw = response.model_dump(mode="json")
        usage = raw.get("usage")
        tokens = TokenUsage(
            input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            cached_input_tokens=(usage.get("input_tokens_details") or {}).get("cached_tokens"),
            reasoning_tokens=(usage.get("output_tokens_details") or {}).get("reasoning_tokens"), raw=usage,
        ) if usage is not None else TokenUsage()
        # Preserve the exact concatenation supplied by output_text, without stripping
        # whitespace/fences, JSON parsing, validation, repair, or refusal-as-success.
        metadata.update(incomplete_details=raw.get("incomplete_details"),
                        provider_error=raw.get("error"),
                        refusals=[part.get("refusal") for item in raw.get("output", [])
                                  if item.get("type") == "message" for part in item.get("content", [])
                                  if part.get("type") == "refusal"])
        return ModelResponse("openai", self.model, raw.get("model"), response.output_text,
                             raw.get("status"), tokens, started_at, perf_counter() - start,
                             response_id=raw.get("id"), request_id=getattr(response, "_request_id", None),
                             raw_response=raw, metadata=metadata)
