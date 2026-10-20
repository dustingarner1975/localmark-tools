"""Small dependency-free client for LocalMark's public API."""

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class LocalMarkError(Exception):
    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class LocalMarkClient:
    def __init__(self, base_url="https://localmark.ai", timeout=10):
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("base_url must be an HTTP(S) URL")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path, params=None):
        params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        url = self.base_url + path + (("?" + urlencode(params)) if params else "")
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "localmark-client/0.3.0"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise LocalMarkError("Response exceeds 4 MB")
                return json.loads(raw)
        except HTTPError as exc:
            detail = f"LocalMark returned HTTP {exc.code}"
            try:
                body = json.loads(exc.read(4096))
                if isinstance(body, dict) and body.get("detail"):
                    detail += f": {body['detail']}"
            except (ValueError, UnicodeDecodeError):
                pass
            finally:
                exc.close()
            raise LocalMarkError(detail, exc.code, exc.headers.get("Retry-After")) from exc
        except URLError as exc:
            raise LocalMarkError(f"Could not reach LocalMark: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise LocalMarkError("LocalMark returned invalid JSON") from exc

    def search(self, q="", *, skill=None, checked_within_hours=None,
               a2a_response_within_hours=None, tls_reachable=None,
               signature=None, limit=20, offset=0):
        return self._get("/api/v1/search", {
            "q": q, "skill": skill, "checked_within_hours": checked_within_hours,
            "a2a_response_within_hours": a2a_response_within_hours,
            "tls_reachable": str(tls_reachable).lower() if tls_reachable is not None else None,
            "signature": signature, "limit": limit, "offset": offset,
        })

    def verify(self, card_url_or_endpoint_or_domain):
        return self._get("/api/v1/verify", {"card_url": card_url_or_endpoint_or_domain})

    def recommend(self, q, *, auth=None, signature=None, protocol=None,
                  checked_within_hours=None, a2a_response_within_hours=None,
                  tls_reachable=None, network=None, asset=None, max_amount=None,
                  limit=10, offset=0):
        """Return LocalMark's shared capability ranking and evidence explanations.

        Requirements narrow results; an empty shortlist is a valid response.
        Price limits use human-readable asset units (0.05 means 0.05 USDC,
        not atomic units) and require both a network and a known asset.
        This reads stored observations and never invokes a publisher's task.
        """
        q = q.strip() if isinstance(q, str) else ""
        if not q or len(q) > 200:
            raise ValueError("q must contain 1..200 characters")
        for name, value, choices in (
            ("auth", auth, (None, "", "none", "declared")),
            ("signature", signature, (None, "", "verified")),
            ("protocol", protocol, (None, "", "JSONRPC", "HTTP+JSON", "GRPC")),
        ):
            if value not in choices:
                raise ValueError(f"Invalid {name}: {value}")
        for name, value, low, high in (
            ("checked_within_hours", checked_within_hours, 1, 168),
            ("a2a_response_within_hours", a2a_response_within_hours, 1, 168),
            ("limit", limit, 1, 20), ("offset", offset, 0, None),
        ):
            if value is None and name not in ("limit", "offset"):
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < low or (high is not None and value > high):
                bounds = f"{low}..{high}" if high is not None else f">= {low}"
                raise ValueError(f"{name} must be an integer {bounds}")
        if tls_reachable is not None and not isinstance(tls_reachable, bool):
            raise ValueError("tls_reachable must be a boolean or None")
        if max_amount is not None:
            if not network or not asset:
                raise ValueError("max_amount requires both network and asset")
            amount_text = str(max_amount)
            if len(amount_text) > 100 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", amount_text):
                raise ValueError("max_amount must be a non-negative decimal without exponent notation (up to 100 characters)")
            try:
                amount = Decimal(amount_text)
            except InvalidOperation as exc:
                raise ValueError("max_amount must be a non-negative decimal") from exc
            if not amount.is_finite() or amount < 0:
                raise ValueError("max_amount must be a non-negative decimal")
            max_amount = format(amount, "f")
        return self._get("/api/v1/recommend", {
            "q": q, "auth": auth, "signature": signature, "protocol": protocol,
            "checked_within_hours": checked_within_hours,
            "a2a_response_within_hours": a2a_response_within_hours,
            "tls_reachable": str(tls_reachable).lower() if tls_reachable is not None else None,
            "network": network, "asset": asset, "max_amount": max_amount,
            "limit": limit, "offset": offset,
        })

    def agent(self, agent_id):
        agent_id = int(agent_id)
        if agent_id < 1:
            raise ValueError("agent_id must be positive")
        return self._get(f"/api/v1/agents/{agent_id}")

    def check_card(self, card_url):
        return self._get("/api/v1/check-card", {"card_url": card_url})

    def health(self):
        return self._get("/api/v1/health")

    def gate(self, target, *, card_hours=24, a2a_hours=None, tls=False, signature=False):
        """Check stored evidence only; never invoke the publisher's endpoint."""
        if card_hours is not None and not 1 <= card_hours <= 8760:
            raise ValueError("card_hours must be 1..8760 or None")
        if a2a_hours is not None and not 1 <= a2a_hours <= 8760:
            raise ValueError("a2a_hours must be 1..8760 or None")
        evidence = self.verify(target)
        checks = {}
        checks["listed"] = evidence.get("listing_status") == "listed"
        latest = evidence.get("card_reachability", {}).get("latest") or {}
        checks["card_reachable"] = latest.get("success") is True
        if card_hours is not None:
            checks["card_recent"] = _recent(latest.get("checked_at"), card_hours)
        if a2a_hours is not None:
            probe = evidence.get("read_only_a2a_probe") or {}
            checks["a2a_response_recent"] = (
                probe.get("state") == "a2a_response" and _recent(probe.get("checked_at"), a2a_hours)
            )
        if tls:
            checks["endpoint_tls_reachable"] = (evidence.get("endpoint_tls") or {}).get("success") is True
        if signature:
            checks["signature_verified"] = (evidence.get("signature") or {}).get("status") == "verified"
        return {"target": target, "passed": all(checks.values()), "checks": checks,
                "agent_id": evidence.get("agent_id"), "profile_url": evidence.get("profile_url"),
                "scope": "Stored LocalMark observations; no live task or payment performed."}


def _recent(value, hours):
    if not value:
        return False
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            return False
        age = datetime.now(timezone.utc) - observed
        return timedelta(0) <= age <= timedelta(hours=hours)
    except (TypeError, ValueError):
        return False
