"""GitHub composite action runner. Values come from environment, never shell code."""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from localmark_client import LocalMarkClient, LocalMarkError
from localmark_client.client import _recent


def _boolean(value, name):
    if value not in ("true", "false"):
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def _hours(value, name, optional=False):
    if optional and value == "":
        return None
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 8760:
        raise ValueError(f"{name} must be an integer 1..8760")
    return int(value)


def run(environment=None, client=None):
    env = os.environ if environment is None else environment
    client = LocalMarkClient() if client is None else client
    target = env.get("LOCALMARK_TARGET", "").strip()
    if not target or len(target) > 2048 or any(ord(c) < 32 for c in target):
        raise ValueError("target must contain 1..2048 characters without control characters")
    mode = env.get("LOCALMARK_MODE", "stored")
    if mode not in ("stored", "check-card"):
        raise ValueError("mode must be stored or check-card")
    card_hours = _hours(env.get("LOCALMARK_CARD_HOURS", "24"), "card-hours")
    a2a_hours = _hours(env.get("LOCALMARK_A2A_HOURS", ""), "a2a-hours", optional=True)
    tls = _boolean(env.get("LOCALMARK_TLS", "true"), "tls")
    signature = _boolean(env.get("LOCALMARK_SIGNATURE", "false"), "signature")
    if mode == "stored":
        return client.gate(target, card_hours=card_hours, a2a_hours=a2a_hours,
                           tls=tls, signature=signature)
    report = client.check_card(target)
    checks = {
        "card_loaded": (report.get("card_fetch") or {}).get("passed") is True,
        "structure_valid": (report.get("structural_check") or {}).get("passed") is True,
        "observation_recent": _recent(report.get("checked_at"), card_hours),
    }
    if tls:
        checks["endpoint_tls_reachable"] = (report.get("endpoint_tls") or {}).get("passed") is True
    if signature:
        checks["signature_verified"] = (report.get("signature") or {}).get("status") == "verified"
    if a2a_hours is not None:
        checks["a2a_response_recent"] = (
            (report.get("read_only_a2a_probe") or {}).get("state") == "a2a_response"
            and _recent(report.get("checked_at"), a2a_hours))
    return {"target": target, "mode": mode, "passed": all(checks.values()),
            "checks": checks, "checked_at": report.get("checked_at"),
            "fixes": (report.get("structural_check") or {}).get("fixes", []),
            "scope": "Publisher-initiated read-only preflight; no agent task or payment performed."}


def main():
    try:
        result = run()
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result.get("passed") is True else 2
    except (LocalMarkError, ValueError) as exc:
        print(f"LocalMark check failed: {exc}", file=sys.stderr)
        if isinstance(exc, LocalMarkError) and exc.retry_after:
            print(f"Retry after {exc.retry_after} seconds", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
