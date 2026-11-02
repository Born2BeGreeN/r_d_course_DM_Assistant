"""Local-only Ollama /api/chat adapter using the shared provider contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import math
import os
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping
from urllib.parse import urlsplit

from dotenv import load_dotenv
import httpx

from src.providers import ModelResponse, ProviderError, Sampling, TokenUsage


@dataclass(frozen=True)
class OllamaConfig:
    model: str = "qwen2.5:3b"
    base_url: str = "http://localhost:11434"
    context_size: int = 8192
    timeout_s: float = 120.0
    sampling: Sampling = field(default_factory=lambda: Sampling(.2, .9, 2048))

    def __post_init__(self):
        url = urlsplit(self.base_url)
        try:
            local = url.hostname == "localhost" or ipaddress.ip_address(url.hostname or "").is_loopback
        except ValueError:
            local = False
        if (not local or url.scheme not in ("http", "https") or url.username or url.password
                or url.query or url.fragment or url.path not in ("", "/")):
            raise ValueError("OLLAMA_BASE_URL must be a loopback HTTP(S) origin, without credentials/path/query")
        if not self.model or not self.model.strip() or ":cloud" in self.model.lower():
            raise ValueError("LOCAL_MODEL must name a local model, not a cloud model")
        if type(self.context_size) is not int or self.context_size <= 0:
            raise ValueError("OLLAMA_CONTEXT_SIZE must be a positive integer")
        if self.sampling.max_output_tokens >= self.context_size:
            raise ValueError("Context must leave room for input in addition to the output budget")
        if isinstance(self.timeout_s, bool) or not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError("LOCAL_TIMEOUT_S must be positive and finite")

    @classmethod
    def from_env(cls, env_path: Path | None = Path(".env")) -> OllamaConfig:
        if env_path is not None:
            load_dotenv(env_path, override=False)
        return cls(model=os.getenv("LOCAL_MODEL", "").strip() or "qwen2.5:3b",
                   base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
                   context_size=int(os.getenv("OLLAMA_CONTEXT_SIZE", "8192")),
                   timeout_s=float(os.getenv("LOCAL_TIMEOUT_S", "120")),
                   sampling=Sampling(float(os.getenv("LOCAL_TEMPERATURE", "0.2")),
                                     float(os.getenv("LOCAL_TOP_P", "0.9")),
                                     int(os.getenv("LOCAL_MAX_OUTPUT_TOKENS", "2048"))))


class OllamaProvider:
    def __init__(self, config: OllamaConfig, *, client: httpx.Client | None = None):
        self.config = config
        self._client = client or httpx.Client(trust_env=False, follow_redirects=False,
                                             transport=httpx.HTTPTransport(retries=0))

    @classmethod
    def from_env(cls, env_path: Path | None = Path(".env")) -> OllamaProvider:
        return cls(OllamaConfig.from_env(env_path))

    def close(self) -> None:
        self._client.close()

    def runtime(self) -> dict:
        """Read local runtime/model metadata only; no pull or model generation."""
        result = {"base_url": self.config.base_url, "requested_model": self.config.model,
                  "ready": False, "blocker": None, "version": None, "model": None,
                  "show": None, "running_models": None}
        try:
            def get(route):
                response = self._client.get(self.config.base_url + route, timeout=min(self.config.timeout_s, 5), follow_redirects=False)
                response.raise_for_status()
                return response.json()
            result["version"] = get("/api/version")
            models = get("/api/tags").get("models", [])
            result["available_model_names"] = [m.get("name") for m in models]
            match = next((m for m in models if m.get("name") == self.config.model or m.get("model") == self.config.model), None)
            if match is None:
                result["blocker"] = "configured_model_missing"
                return result
            result["model"] = match
            response = self._client.post(self.config.base_url + "/api/show", json={"model": self.config.model},
                                         timeout=min(self.config.timeout_s, 5), follow_redirects=False)
            response.raise_for_status()
            result["show"] = response.json()
            if any(data.get("remote_host") or data.get("remote_model") for data in (match, result["show"])):
                result["blocker"] = "remote_model_forbidden"
                return result
            capabilities = result["show"].get("capabilities")
            if capabilities is not None and "completion" not in capabilities:
                result["blocker"] = "model_does_not_support_completion"
                return result
            info = result["show"].get("model_info", {})
            lengths = [v for k, v in info.items() if k.endswith(".context_length") and type(v) is int]
            if lengths and self.config.context_size > min(lengths):
                result["blocker"] = "requested_context_exceeds_model_limit"
                return result
            result["running_models"] = get("/api/ps")
            result["ready"] = True
        except httpx.ConnectError:
            result["blocker"] = "service_unavailable"
        except httpx.TimeoutException:
            result["blocker"] = "runtime_probe_timeout"
        except httpx.HTTPStatusError as exc:
            result["blocker"] = "runtime_probe_http_error"
            result["http_status"] = exc.response.status_code
        except (httpx.RequestError, ValueError, TypeError, AttributeError):
            result["blocker"] = "invalid_runtime_response"
        return result

    def generate(self, text: str, prompt: str, schema: dict,
                 sampling: Sampling | Mapping[str, Any], timeout_s: float) -> ModelResponse:
        if not isinstance(sampling, Sampling):
            sampling = Sampling(**sampling)
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be positive and finite")
        start = perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        metadata = {"http_retries": 0, "http_attempts": 0, "context_size_requested": self.config.context_size,
                    "temperature": sampling.temperature, "top_p": sampling.top_p,
                    "max_output_tokens": sampling.max_output_tokens, "timeout_s": timeout_s,
                    "context_detection": "Best effort: explicit flags/errors and reported token/context limits only; silent server-side input truncation cannot be ruled out without tokenizer/server telemetry."}
        raw = None
        content = ""
        usage = TokenUsage()
        returned_model = None
        finish = None

        def failed(kind, status=None, detail=None):
            return ProviderError(ModelResponse("ollama", self.config.model, returned_model, content,
                                 finish or "error", usage, started_at, perf_counter() - start,
                                 raw_response=raw, error={"type": kind, "http_status": status, "detail": detail},
                                 metadata=dict(metadata)))

        if sampling.max_output_tokens >= self.config.context_size:
            raise failed("context_budget_invalid")
        try:
            metadata["http_attempts"] = 1
            response = self._client.post(self.config.base_url.rstrip("/") + "/api/chat", timeout=float(timeout_s), follow_redirects=False,
                json={"model": self.config.model, "stream": False, "format": schema,
                      "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
                      "options": {"temperature": sampling.temperature, "top_p": sampling.top_p,
                                  "num_ctx": self.config.context_size, "num_predict": sampling.max_output_tokens}})
        except httpx.TimeoutException:
            raise failed("local_timeout") from None
        except httpx.ConnectError:
            raise failed("service_unavailable") from None
        except httpx.RequestError:
            raise failed("local_transport_error") from None
        try:
            raw = response.json()
        except ValueError:
            raise failed("non_json_runtime_response", response.status_code) from None
        if not isinstance(raw, dict):
            raise failed("invalid_runtime_response", response.status_code)
        metadata["retry_after"] = response.headers.get("retry-after")
        error = raw.get("error")
        if response.status_code >= 300 or error:
            message = str(error or "").lower()
            kind = "local_http_error"
            if "context" in message and any(w in message for w in ("exceed", "length", "large", "limit", "overflow")):
                kind = "context_overflow"
            elif "model" in message and any(w in message for w in ("not found", "does not exist", "missing")):
                kind = "configured_model_missing"
            elif any(w in message for w in ("unsupported", "not support", "invalid option", "unknown option", "invalid parameter")):
                kind = "unsupported_parameter_or_format"
            raise failed(kind, response.status_code, error)
        returned_model = raw.get("model")
        finish = raw.get("done_reason")
        message = raw.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise failed("missing_message_content")
        content = message["content"]
        counts = {key: raw.get(key) for key in ("prompt_eval_count", "eval_count", "prompt_eval_cached_count")}
        if any(value is not None and (type(value) is not int or value < 0) for value in counts.values()):
            raise failed("invalid_token_counters")
        inp, out = counts["prompt_eval_count"], counts["eval_count"]
        usage = TokenUsage(inp, out, inp + out if inp is not None and out is not None else None,
                           counts["prompt_eval_cached_count"], None, counts)
        metadata.update(created_at=raw.get("created_at"), server_durations_ns={k: raw.get(k) for k in
                        ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")})
        metadata["server_warnings"] = raw.get("warnings", raw.get("warning"))
        if returned_model != self.config.model:
            raise failed("returned_model_mismatch")
        if raw.get("done") is not True:
            raise failed("incomplete_response")
        if any(raw.get(k) is True for k in ("truncated", "prompt_truncated", "context_overflow")):
            raise failed("context_truncated")
        warning = str(metadata["server_warnings"] or "").lower()
        if "truncat" in warning and any(word in warning for word in ("input", "prompt", "context")):
            raise failed("context_truncated")
        if finish == "length" or (out is not None and out >= sampling.max_output_tokens):
            raise failed("output_truncated_or_limit_reached")
        if inp is not None and inp >= self.config.context_size:
            raise failed("context_capacity_reached")
        if inp is not None and out is not None and inp + out >= self.config.context_size:
            raise failed("context_window_saturated")
        if raw.get("context_length") is not None:
            if type(raw["context_length"]) is not int or raw["context_length"] <= 0:
                raise failed("invalid_reported_context_length")
            if raw["context_length"] < self.config.context_size:
                raise failed("context_configuration_not_applied")
        if finish != "stop" or not content.strip():
            raise failed("unexpected_finish_or_empty_output")
        return ModelResponse("ollama", self.config.model, returned_model, content, finish, usage,
                             started_at, perf_counter() - start, raw_response=raw, metadata=metadata)
