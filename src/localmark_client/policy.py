"""Strict, portable selection policies. Policies contain requirements, never credentials."""

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path


POLICY_KEYS = frozenset({
    "q", "auth", "signature", "protocol", "checked_within_hours",
    "a2a_response_within_hours", "tls_reachable", "network", "asset",
    "max_amount", "limit", "offset",
})


def validate_policy(policy):
    """Return a validated copy of a recommendation policy, rejecting unknown keys.

    q may be omitted when the caller supplies a query separately. A policy is
    only a saved search; it never authorizes a task, payment, or credentials.
    """
    if not isinstance(policy, dict):
        raise ValueError("Policy must be a JSON object")
    if any(not isinstance(key, str) for key in policy):
        raise ValueError("Policy field names must be strings")
    unknown = sorted(set(policy) - POLICY_KEYS)
    if unknown:
        raise ValueError("Unknown policy field(s): " + ", ".join(map(str, unknown)))
    result = dict(policy)
    if "q" in result:
        if not isinstance(result["q"], str) or not 1 <= len(result["q"].strip()) <= 200:
            raise ValueError("q must contain 1..200 characters")
        result["q"] = result["q"].strip()
    for name, choices in (("auth", ("none", "declared")),
                          ("signature", ("verified",)),
                          ("protocol", ("JSONRPC", "HTTP+JSON", "GRPC"))):
        if name in result and result[name] not in choices:
            raise ValueError(f"Invalid {name}: {result[name]}")
    for name, low, high in (("checked_within_hours", 1, 168),
                            ("a2a_response_within_hours", 1, 168),
                            ("limit", 1, 20), ("offset", 0, 100000)):
        if name in result:
            value = result[name]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be an integer {low}..{high}")
    if "tls_reachable" in result and not isinstance(result["tls_reachable"], bool):
        raise ValueError("tls_reachable must be a boolean")
    for name in ("network", "asset"):
        if name in result:
            value = result[name]
            if not isinstance(value, str) or not 1 <= len(value) <= 200 or any(ord(c) < 33 for c in value):
                raise ValueError(f"{name} must be a non-empty public identifier up to 200 characters")
    if "max_amount" in result:
        if not result.get("network") or not result.get("asset"):
            raise ValueError("max_amount requires both network and asset")
        value = result["max_amount"]
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise ValueError("max_amount must be a non-negative decimal")
        amount_text = str(value)
        if len(amount_text) > 100 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", amount_text):
            raise ValueError("max_amount must be a non-negative decimal without exponent notation (up to 100 characters)")
        try:
            amount = Decimal(amount_text)
        except InvalidOperation as exc:
            raise ValueError("max_amount must be a non-negative decimal") from exc
        if not amount.is_finite() or amount < 0:
            raise ValueError("max_amount must be a non-negative decimal")
        result["max_amount"] = format(amount, "f")
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate policy field: {key}")
        result[key] = value
    return result


def load_policy(path):
    """Load a UTF-8 JSON selection policy (maximum 64 KiB)."""
    try:
        with Path(path).open("rb") as source:
            data = source.read(65537)
        if len(data) > 65536:
            raise ValueError("Policy exceeds 64 KiB")
        policy = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite policy number")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read policy: {exc}") from exc
    return validate_policy(policy)
