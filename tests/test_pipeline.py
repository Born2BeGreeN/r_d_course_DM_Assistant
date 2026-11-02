"""Synthetic mocked extractions and temporary budget ledgers only."""

from dataclasses import asdict
import json

import pytest

from src.budget import Budget, BudgetExceeded, NANO, history_events, price_usage, reservation, units
from src.pipeline import Operations, Pipeline, card_validation, retry_after_seconds, write_once
from src.providers import ModelResponse, ProviderError, Sampling, TokenUsage
from src.schema import card_json_schema

PRICING = {"model_ids": ["gpt-4o-mini"], "uncached_input_per_1m": .15,
           "cached_input_per_1m": .075, "output_per_1m": .6, "reservation_input_tokens": 128000}
CARD = {"title": "Synthetic test adventure", "language": "en", "recommended_level": None,
        "hook": None, "npcs": [], "locations": [], "threats": [], "rewards": []}


def reply(text=None, *, error=None, metadata=None, usage=True, finish="completed"):
    return ModelResponse("openai", "gpt-4o-mini", "gpt-4o-mini", json.dumps(CARD) if text is None else text,
                         finish, TokenUsage(100, 20, 120, 0, 0) if usage else TokenUsage(),
                         "synthetic-time", .01, error=error,
                         metadata={"sdk_call_count": 1, "sdk_retries": 0} | (metadata or {}))


class Fake:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, text, prompt, schema, sampling, timeout_s):
        self.calls.append((text, prompt, schema, sampling, timeout_s))
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def execute(tmp_path, replies, *, operations=None, limit=5, clock=None):
    fake = Fake(replies)
    budget = Budget(tmp_path / "budget.sqlite3", limit)
    kw = clock or {"sleep": lambda _: None}
    pipeline = Pipeline(fake, "openai", operations or Operations(), PRICING, budget, **kw)
    result = pipeline.extract("Synthetic source", "Synthetic extraction instructions", "Fixed synthetic repair instructions",
                              card_json_schema(), Sampling(.2, .9), {"fixture": "synthetic-experiment"}, tmp_path / "job")
    return result, fake, budget


def test_success_persists_raw_usage_before_validation(tmp_path, monkeypatch):
    from src import pipeline as module
    original = module.card_validation
    def verify(text):
        raw = json.loads((tmp_path / "job/attempt_01.response.json").read_text())
        assert raw["response"]["raw_text"] == text
        assert raw["response"]["usage"]["input_tokens"] == 100
        return original(text)
    monkeypatch.setattr(module, "card_validation", verify)
    result, fake, budget = execute(tmp_path, [reply()])
    try:
        assert result["first_pass_valid"] and result["final_valid"]
        assert result["final_card"] == CARD and len(fake.calls) == 1
        assert result["cost"]["estimated_usd"] > 0
    finally:
        budget.close()


def test_successful_repair_uses_source_invalid_answer_errors_and_same_schema(tmp_path):
    result, fake, budget = execute(tmp_path, [reply('{"invalid":true}'), reply()])
    try:
        assert not result["first_pass_valid"] and result["final_valid"]
        assert result["failure"] is None and result["repair_count"] == 1
        assert len(fake.calls) == 2 and fake.calls[1][1] == "Fixed synthetic repair instructions"
        envelope = json.loads(fake.calls[1][0])
        assert envelope["source_text"] == "Synthetic source"
        assert envelope["invalid_answer"] == '{"invalid":true}' and envelope["validation_errors"]
        assert fake.calls[0][2] == fake.calls[1][2] == card_json_schema()
    finally:
        budget.close()


def test_failed_repair_stops_without_second_repair(tmp_path):
    result, fake, budget = execute(tmp_path, [reply("not json"), reply("still not json")])
    try:
        assert result["status"] == "failed" and result["final_card"] is None
        assert result["repair_count"] == 1 and result["actual_call_attempts"] == 2 and len(fake.calls) == 2
    finally:
        budget.close()


def test_retry_exhaustion_is_not_schema_repair_and_unknown_cost_is_reserved(tmp_path):
    failure = ProviderError(reply("", error={"type": "APITimeoutError"}, usage=False))
    result, fake, budget = execute(tmp_path, [failure, failure])
    try:
        assert len(fake.calls) == 2 and result["transport_retry_count"] == 1
        assert result["repair_count"] == 0 and result["final_card"] is None
        assert result["cost"]["estimated_usd"] is None and result["cost"]["unknown_usage_attempts"] == 2
        assert budget.total() == 2 * reservation(PRICING, 2048)
    finally:
        budget.close()


def test_generation_and_repair_transport_limits_total_four(tmp_path):
    failure = ProviderError(reply("", error={"type": "APIConnectionError"}, usage=False))
    result, fake, budget = execute(tmp_path, [failure, reply("bad"), failure, reply()])
    try:
        assert result["final_valid"] and result["actual_call_attempts"] == len(fake.calls) == 4
        assert result["transport_retry_count"] == 2 and result["repair_count"] == 1
    finally:
        budget.close()


def test_budget_enforcement_prevents_any_request(tmp_path):
    result, fake, budget = execute(tmp_path, [], limit=.001)
    try:
        assert fake.calls == [] and result["stop_batch_reason"] == "budget_exhausted"
        assert result["actual_call_attempts"] == 0 and budget.total() == 0
    finally:
        budget.close()


def test_budget_cumulative_across_new_instances_and_crashed_reservations(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    budget = Budget(path, .03)
    budget.reserve(reservation(PRICING, 2048), "synthetic-smoke")
    budget.close()  # Crash: reservation remains, never assumed free.
    budget = Budget(path, .03)
    try:
        with pytest.raises(BudgetExceeded):
            budget.reserve(reservation(PRICING, 2048), "synthetic-new-run-repair")
    finally:
        budget.close()


def test_cached_and_thinking_tokens_not_double_billed():
    assert price_usage({"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 200, "reasoning_tokens": 50}, PRICING) == units(.00024)
    assert price_usage({"input_tokens": None, "output_tokens": 100}, PRICING) is None


def test_retry_after_respected_and_deadline_bounds_wait(tmp_path):
    now, waits = [0.], []
    def sleep(delay):
        waits.append(delay)
        now[0] += delay
    failure = ProviderError(reply("", error={"type": "RateLimitError", "http_status": 429}, metadata={"retry_after": "2"}, usage=False))
    result, fake, budget = execute(tmp_path, [failure, reply()], clock={"clock": lambda: now[0], "sleep": sleep})
    budget.close()
    assert waits == [2.] and result["final_valid"] and len(fake.calls) == 2
    assert retry_after_seconds("Thu, 01 Jan 1970 00:00:04 GMT", now=lambda: 1) == 3
    other = tmp_path / "other"
    result, fake, budget = execute(other, [failure], operations=Operations(provider_request_deadline_s=1),
                                 clock={"clock": lambda: 0, "sleep": lambda _: pytest.fail("Cannot sleep beyond deadline")})
    budget.close()
    assert len(fake.calls) == 1 and result["failure"] == "retry_after_exceeds_deadline_or_bound"


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_invalid_credentials_or_global_configuration_stops_batch(tmp_path, status):
    failure = ProviderError(reply("", error={"type": "APIStatusError", "http_status": status}, usage=False))
    result, fake, budget = execute(tmp_path, [failure])
    budget.close()
    assert len(fake.calls) == 1 and result["stop_batch_reason"] == "APIStatusError"


def test_resume_requires_identical_identity_and_unchanged_raw_attempt(tmp_path):
    result, fake, budget = execute(tmp_path, [reply()])
    pipeline = Pipeline(fake, "openai", Operations(), PRICING, budget)
    try:
        same = pipeline.extract("Synthetic source", "Synthetic extraction instructions", "Fixed synthetic repair instructions", card_json_schema(), Sampling(.2, .9), {"fixture": "synthetic-experiment"}, tmp_path / "job")
        assert same == result and len(fake.calls) == 1
        with pytest.raises(ValueError, match="identity mismatch"):
            pipeline.extract("Different input", "prompt", "repair", {}, Sampling(.8, .9), {"fixture": "changed"}, tmp_path / "job")
        (tmp_path / "job/attempt_01.response.json").write_text("tampered")
        with pytest.raises(ValueError, match="attempt changed"):
            pipeline.extract("Synthetic source", "Synthetic extraction instructions", "Fixed synthetic repair instructions", card_json_schema(), Sampling(.2, .9), {"fixture": "synthetic-experiment"}, tmp_path / "job")
    finally:
        budget.close()


def test_historical_smoke_usage_is_importable_without_double_charging(tmp_path):
    results = tmp_path / "results"
    write_once(results / "smoke.json", {"external_provider_calls": 1, "model_response": asdict(reply())})
    events = history_events(results, PRICING)
    assert len(events) == 1 and events[0]["known"]
    budget = Budget(tmp_path / "ledger.sqlite3")
    try:
        for _ in range(2):
            for event in events:
                budget.import_charge(event["id"], event["amount"], event["known"])
        assert budget.total() == events[0]["amount"]
    finally:
        budget.close()


def test_unknown_untracked_external_smoke_reserves_entire_budget(tmp_path):
    write_once(tmp_path / "results/smoke.json", {"external_provider_calls": 1, "model_response": None})
    events = history_events(tmp_path / "results", PRICING)
    assert len(events) == 1 and events[0]["amount"] == units(5) and not events[0]["known"]


def test_schema_failures_include_duplicate_keys_and_strict_npcs():
    assert card_validation('{"title":null,"title":"duplicate"}')[0] is None
    assert card_validation(json.dumps(CARD | {"npcs": [{"name": "Synthetic NPC"}]}))[0] is None


def test_quota_failure_stops_without_transport_retry(tmp_path):
    failure = ProviderError(reply('', error={'type':'RateLimitError','http_status':429}, metadata={'api_error_code':'insufficient_quota'}, usage=False))
    result, fake, budget = execute(tmp_path, [failure])
    budget.close()
    assert result['stop_batch_reason'] == 'RateLimitError' and len(fake.calls) == 1


def test_lower_configured_attempt_cap_is_enforced(tmp_path):
    failure = ProviderError(reply('', error={'type':'APIConnectionError'}, usage=False))
    result, fake, budget = execute(tmp_path, [failure, reply('invalid'), failure], operations=Operations(max_call_attempts=3))
    budget.close()
    assert len(fake.calls) == result['actual_call_attempts'] == 3
    assert not result['final_valid']


def test_history_reconciles_current_raw_and_manual_adjustment(tmp_path):
    result, fake, budget = execute(tmp_path, [reply()])
    before = budget.total()
    write_once(tmp_path / 'adjustment.json', {'kind':'manual_budget_adjustment','reference':'synthetic-outside-app','usd':.1})
    for event in history_events(tmp_path, PRICING):
        budget.import_charge(event['id'], event['amount'], event['known'])
    assert budget.total() == before + units(.1)
    budget.close()


def test_result_checksum_rejects_changed_terminal_card(tmp_path):
    result, fake, budget = execute(tmp_path, [reply()])
    (tmp_path / 'job/result.json').write_text('{}')
    try:
        with pytest.raises(ValueError, match='terminal result hash'):
            Pipeline(fake, 'openai', Operations(), PRICING, budget).extract('source','prompt','repair',card_json_schema(),Sampling(.2,.9),{},tmp_path/'job')
    finally:
        budget.close()


def test_unknown_adapter_exception_preserves_unknown_usage_and_reservation(tmp_path):
    result, fake, budget = execute(tmp_path, [RuntimeError('synthetic failure')])
    budget.close()
    assert result['actual_call_attempts'] == 1 and result['usage']['input_tokens'] is None
    assert result['cost']['estimated_usd'] is None
