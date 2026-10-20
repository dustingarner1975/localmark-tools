"""Small dependency-free client for LocalMark's public API."""

import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from .policy import load_policy, validate_policy


class LocalMarkError(Exception):
    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class LocalMarkClient:
    def __init__(self, base_url="https://localmark.ai", timeout=10, *, project_id=None):
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("base_url must be an HTTP(S) URL")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.project_id = None
        if project_id is not None:
            try:
                identifier = UUID(str(project_id))
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError("project_id must be a random UUIDv4, never a secret or user identifier") from exc
            if identifier.version != 4:
                raise ValueError("project_id must be a random UUIDv4, never a secret or user identifier")
            self.project_id = str(identifier)

    def _get(self, path, params=None):
        params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        url = self.base_url + path + (("?" + urlencode(params)) if params else "")
        headers = {"Accept": "application/json", "User-Agent": "localmark-client/0.4.0"}
        if self.project_id is not None:
            headers["X-LocalMark-Project"] = self.project_id
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise LocalMarkError("Response exceeds 4 MB")
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise LocalMarkError("LocalMark returned a JSON value instead of an object")
                return result
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

    def recommend(self, q=None, *, policy=None, auth=None, signature=None, protocol=None,
                  checked_within_hours=None, a2a_response_within_hours=None,
                  tls_reachable=None, network=None, asset=None, max_amount=None,
                  limit=None, offset=None):
        """Return shared capability rankings, optionally using a saved JSON policy.

        Explicit non-None arguments override saved requirements. A policy may
        be a mapping or local JSON path. Requirements never authorize a task,
        a payment, credential sharing, or an automatic connection.
        """
        params = (load_policy(policy) if isinstance(policy, str) or hasattr(policy, "__fspath__")
                  else validate_policy(policy)) if policy is not None else {}
        supplied = {
            "q": q, "auth": auth, "signature": signature, "protocol": protocol,
            "checked_within_hours": checked_within_hours,
            "a2a_response_within_hours": a2a_response_within_hours,
            "tls_reachable": tls_reachable, "network": network, "asset": asset,
            "max_amount": max_amount, "limit": limit, "offset": offset,
        }
        params.update({key: value for key, value in supplied.items() if value is not None})
        # Legacy optional blank strings are equivalent to absent requirements.
        params = {key: value for key, value in params.items() if value != ""}
        params = validate_policy(params)
        if not params.get("q"):
            raise ValueError("q must contain 1..200 characters (supply a query or policy q)")
        params.setdefault("limit", 10)
        params.setdefault("offset", 0)
        if "tls_reachable" in params:
            params["tls_reachable"] = str(params["tls_reachable"]).lower()
        return self._get("/api/v1/recommend", params)

    def connection_plan(self, target):
        """Read public connection metadata; never connect to or invoke the agent.

        target is a LocalMark numeric agent ID, card URL, endpoint URL or domain.
        The plan may describe required authentication but never contains keys.
        """
        target = str(target).strip()
        if not target or len(target) > 2048 or any(ord(c) < 32 for c in target):
            raise ValueError("target must contain 1..2048 characters without control characters")
        return self._get("/api/v1/connection-plan", {"target": target})

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
        if card_hours is not None and (isinstance(card_hours, bool) or not isinstance(card_hours, int) or not 1 <= card_hours <= 8760):
            raise ValueError("card_hours must be 1..8760 or None")
        if a2a_hours is not None and (isinstance(a2a_hours, bool) or not isinstance(a2a_hours, int) or not 1 <= a2a_hours <= 8760):
            raise ValueError("a2a_hours must be 1..8760 or None")
        if not isinstance(tls, bool) or not isinstance(signature, bool):
            raise ValueError("tls and signature must be booleans")
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
            endpoint_tls = evidence.get("endpoint_tls") or {}
            checks["endpoint_tls_reachable"] = endpoint_tls.get("success") is True
            if card_hours is not None:
                checks["endpoint_tls_recent"] = _recent(endpoint_tls.get("checked_at"), card_hours)
        if signature:
            checks["signature_verified"] = (evidence.get("signature") or {}).get("status") == "verified"
        return {"target": target, "passed": all(checks.values()), "checks": checks,
                "agent_id": evidence.get("agent_id"), "profile_url": evidence.get("profile_url"),
                "scope": "Stored LocalMark observations; no live task or payment performed."}


def _recent(value, hours):
    if not isinstance(value, str) or not value:
        return False
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            return False
        age = datetime.now(timezone.utc) - observed
        return timedelta(0) <= age <= timedelta(hours=hours)
    except (TypeError, ValueError):
        return False
