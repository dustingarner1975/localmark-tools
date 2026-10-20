"""Small dependency-free client for LocalMark's public API."""

import json
from datetime import datetime, timedelta, timezone
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
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "localmark-client/0.2.0"})
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
