"""Durable, atomic cumulative homework API budget; no provider calls."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

NANO = 1_000_000_000


def units(usd) -> int:
    value = Decimal(str(usd))
    if not value.is_finite() or value < 0:
        raise ValueError("Cost must be finite and nonnegative")
    return int((value * NANO).to_integral_value(rounding=ROUND_CEILING))


class BudgetExceeded(RuntimeError):
    pass


def reservation(pricing: dict, max_output_tokens: int) -> int:
    return units((Decimal(pricing["reservation_input_tokens"]) * Decimal(str(pricing["uncached_input_per_1m"]))
                  + Decimal(max_output_tokens) * Decimal(str(pricing["output_per_1m"]))) / 1_000_000)


def price_usage(usage: dict | None, pricing: dict) -> int | None:
    if not usage:
        return None
    inp, out = usage.get("input_tokens"), usage.get("output_tokens")
    cached = usage.get("cached_input_tokens")
    if any(type(v) is not int or v < 0 for v in (inp, out)):
        return None
    if cached is None:
        cached = 0  # Upper estimate: no unverified cache discount.
    if type(cached) is not int or not 0 <= cached <= inp:
        return None
    thinking = usage.get("reasoning_tokens")
    if thinking is not None and (type(thinking) is not int or not 0 <= thinking <= out):
        return None
    return units((Decimal(inp - cached) * Decimal(str(pricing["uncached_input_per_1m"]))
                  + Decimal(cached) * Decimal(str(pricing["cached_input_per_1m"]))
                  + Decimal(out) * Decimal(str(pricing["output_per_1m"]))) / 1_000_000)


class Budget:
    def __init__(self, path: Path, limit_usd=5):
        self.limit = units(limit_usd)
        if not 0 < self.limit <= units(5):
            raise ValueError("Cumulative homework budget must be in (0, USD 5]")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS charges (id TEXT PRIMARY KEY, identity TEXT NOT NULL, "
                        "reserved INTEGER NOT NULL, accounted INTEGER NOT NULL, state TEXT NOT NULL, usage TEXT)")

    def close(self):
        self.db.close()

    def total(self) -> int:
        return self.db.execute("SELECT COALESCE(SUM(accounted),0) FROM charges").fetchone()[0]

    def reserve(self, amount: int, identity: str, charge_id: str | None = None) -> str:
        charge_id = charge_id or uuid.uuid4().hex
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if amount < 0 or self.total() + amount > self.limit:
                raise BudgetExceeded("Cumulative USD 5 homework budget cannot cover another conservative reservation")
            self.db.execute("INSERT INTO charges VALUES (?,?,?,?,?,?)",
                            (charge_id, identity, amount, amount, "reserved", None))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return charge_id

    def settle(self, charge_id: str, usage: dict | None, pricing: dict, *, no_call=False) -> dict:
        row = self.db.execute("SELECT reserved FROM charges WHERE id=?", (charge_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown budget reservation")
        estimate = 0 if no_call else price_usage(usage, pricing)
        accounted = row[0] if estimate is None else estimate
        # If a provider reports a larger billable usage, record it honestly even
        # above the reservation; stop all future calls rather than hide overage.
        self.db.execute("UPDATE charges SET accounted=?,state=?,usage=? WHERE id=?",
                        (accounted, "unknown_usage" if estimate is None else "usage_estimate", json.dumps(usage), charge_id))
        return {"budget_charge_id": charge_id, "estimated_usd": estimate / NANO if estimate is not None else None,
                "accounted_usd": accounted / NANO, "reserved_usd": row[0] / NANO,
                "usage_known": estimate is not None, "cumulative_accounted_usd": self.total() / NANO}

    def import_charge(self, identity: str, amount: int, known: bool) -> None:
        previous = self.db.execute("SELECT accounted,state FROM charges WHERE id=?", (identity,)).fetchone()
        if previous:
            # Raw responses can reconcile a reservation left by a crash.
            if previous[1] == "reserved" and known:
                self.db.execute("UPDATE charges SET accounted=?,state=? WHERE id=?", (amount, "imported_estimate", identity))
            elif amount > previous[0]:
                self.db.execute("UPDATE charges SET accounted=?,state=? WHERE id=?", (amount, "conservative_audit_increase", identity))
            return
        # Historical spend must be recorded even when it already exhausts budget.
        self.db.execute("INSERT INTO charges VALUES (?,?,?,?,?,?)",
                        (identity, "historical_or_manual", amount, amount,
                         "imported_estimate" if known else "unknown_history", None))


def history_events(results: Path, pricing: dict) -> list[dict]:
    """Audit all raw attempts/smokes; deduplicate durable pipeline call IDs.

    Malformed JSON stops the audit. Legacy unknown-model/unknown-call history
    reserves the entire budget until the user reconciles it; never assume free.
    """
    events = {}
    for path in sorted(results.rglob("*.json")) if results.exists() else []:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"Unreadable historical result needs budget audit: {path}") from exc

        found = [0]

        def visit(node, location=""):
            if isinstance(node, list):
                for index, child in enumerate(node):
                    visit(child, f"{location}/{index}")
                return
            if not isinstance(node, dict):
                return
            if node.get("kind") == "manual_budget_adjustment":
                key = "manual_" + node["reference"]
                amount = units(node["usd"])
                if key in events and events[key]["amount"] != amount:
                    raise ValueError("Conflicting historical manual spend reference")
                events[key] = {"id": key, "amount": amount, "known": True}
                return
            if node.get("kind") == "call_intent" and node.get("provider") == "openai":
                key = node["budget_charge_id"]
                events.setdefault(key, {"id": key, "amount": node["reservation_units"], "known": False})
            response = node.get("response")
            if isinstance(response, dict) and response.get("provider") == "openai":
                key = node.get("budget_charge_id")
                record_response(response, key, location, node.get("pricing") or pricing)
                return
            if node.get("provider") == "openai" and "requested_model" in node and "usage" in node:
                record_response(node, None, location, pricing)
                return
            for key, child in node.items():
                visit(child, location + "/" + key)

        def record_response(response, key, location, profile):
            found[0] += 1
            key = key or response.get("response_id") or response.get("request_id")
            key = key or "legacy_" + hashlib.sha256((str(path.resolve()) + location).encode()).hexdigest()
            metadata = response.get("metadata") or {}
            no_call = metadata.get("sdk_call_count") == 0
            model = response.get("returned_model") or response.get("requested_model")
            known_model = model in profile["model_ids"]
            amount = price_usage(response.get("usage"), profile) if known_model else None
            if no_call:
                amount = 0
            events[key] = {"id": key, "amount": amount if amount is not None else
                           reservation(profile, metadata.get("max_output_tokens", 16384)) if known_model else units(5),
                           "known": amount is not None}

        visit(value)
        if isinstance(value, dict) and value.get("external_provider_calls", 0) > found[0]:
            key = "unknown_history_" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()
            events[key] = {"id": key, "amount": units(5), "known": False}
    return list(events.values())
