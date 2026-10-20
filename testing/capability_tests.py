"""Explicitly opted-in, bounded synthetic endpoint tests. Never an A2A task runner.

Only publisher-advertised, same-host, free dedicated test endpoints are eligible.
This module deliberately has no import-time network or database side effects.
"""

import base64
import hashlib
import http.client
import ipaddress
import json
import math
import os
import queue
import re
import socket
import ssl
import threading
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlsplit


EXTENSION_URI = "https://localmark.ai/extensions/capability-tests/v1"
MANIFEST_PATH = "/.well-known/localmark-tests.json"
FIXTURE_VERSION = "1"
SCOPE = ("A publisher-authorized synthetic test of a dedicated free test endpoint. "
         "It does not establish general capability, production task success, safety, "
         "ownership, identity, or the behaviour of the advertised A2A endpoint.")
PUBLIC_WHERE = "a.status='verified' AND NOT EXISTS (SELECT 1 FROM moderation_blocks b WHERE b.card_url=a.card_url) AND NOT EXISTS (SELECT 1 FROM agent_aliases x WHERE x.alias_agent_id=a.id)"
DATABASE_URL = None
SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_test_runs (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 agent_id bigint NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
 card_url text NOT NULL,
 checked_at timestamptz NOT NULL DEFAULT now(),
 status text NOT NULL,
 reason_code text NOT NULL,
 manifest_sha256 text,
 consent_expires_at timestamptz,
 results jsonb NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS capability_test_runs_agent_idx ON capability_test_runs(agent_id, checked_at DESC);
CREATE TABLE IF NOT EXISTS capability_test_requests (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 agent_id bigint NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
 host text NOT NULL,
 requested_at timestamptz NOT NULL DEFAULT now(),
 test_id text NOT NULL,
 endpoint text NOT NULL,
 UNIQUE(agent_id, test_id, requested_at)
);
CREATE INDEX IF NOT EXISTS capability_test_requests_host_idx ON capability_test_requests(host,requested_at DESC);
"""


class TestPolicyError(ValueError):
    """An input is ineligible; no test request should be sent."""


def utcnow():
    return datetime.now(timezone.utc)


def configure(database_url, public_where=PUBLIC_WHERE):
    global DATABASE_URL, PUBLIC_WHERE
    DATABASE_URL = database_url
    PUBLIC_WHERE = public_where


def _tiny_pdf():
    lines = ["LocalMark synthetic invoice", "Invoice LM-TEST-0042", "Total EUR 12.50"]
    stream = "BT /F1 12 Tf 40 750 Td " + " 0 -18 Td ".join("(" + s + ") Tj" for s in lines) + " ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               f"<< /Length {len(stream.encode('ascii'))} >>\nstream\n{stream}\nendstream"]
    value = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(value))
        value += f"{i} 0 obj\n{obj}\nendobj\n".encode("ascii")
    start = len(value)
    value += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode("ascii")
    value += b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:])
    value += f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode("ascii")
    return base64.b64encode(value).decode("ascii")


FIXTURES = {
    "json_transform": {
        "request": {"fixture_version": FIXTURE_VERSION, "kind": "json_transform",
                    "input": {"rows": [{"id": "LM-001", "quantity": 2}, {"id": "LM-002", "quantity": 3}]},
                    "instruction": "Return ids sorted descending and the sum of quantity as total, in an output object."},
        "assertion": {"type": "exact_json", "expected": {"output": {"ids": ["LM-002", "LM-001"], "total": 5}}},
        "scope": "One fixed two-row JSON sorting and arithmetic example; not a general reasoning test.",
    },
    "pdf_extraction": {
        "request": {"fixture_version": FIXTURE_VERSION, "kind": "pdf_extraction",
                    "input": {"media_type": "application/pdf", "pdf_base64": _tiny_pdf()},
                    "instruction": "Extract the three text lines in reading order; return only a text property."},
        "assertion": {"type": "exact_json", "expected": {"text": "LocalMark synthetic invoice\nInvoice LM-TEST-0042\nTotal EUR 12.50"}},
        "scope": "One synthetic, single-page text PDF; does not test scans, OCR, complex layouts, or real documents.",
    },
    "geocoding": {
        "request": {"fixture_version": FIXTURE_VERSION, "kind": "geocoding",
                    "input": {"place": "Lisbon, Portugal"},
                    "instruction": "Return numeric latitude and longitude for the city centre in decimal degrees."},
        "assertion": {"type": "coordinates", "latitude": 38.7223, "longitude": -9.1393, "tolerance_degrees": 0.15},
        "scope": "One public city-level place name, with 0.15 degree tolerance; does not test precise or global coverage.",
    },
}


def fixture(kind):
    """Return an independent public fixture (callers cannot mutate the source)."""
    if kind not in FIXTURES:
        raise TestPolicyError("unsupported_test_kind")
    return json.loads(json.dumps(FIXTURES[kind]))


def _url(url, *, same_host=None, path=None, test_endpoint=False):
    if (not isinstance(url, str) or len(url) > 2000 or not url.isascii() or
            any(c.isspace() or ord(c) < 33 for c in url) or "\\" in url):
        raise TestPolicyError("invalid_https_url")
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or "." not in parsed.hostname
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.hostname.endswith(".")):
            raise TestPolicyError("public_https_443_required")
    except ValueError as exc:
        raise TestPolicyError("invalid_https_url") from exc
    host = parsed.hostname.lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise TestPolicyError("hostname_required")
    if len(host) > 253 or (same_host and host != same_host):
        raise TestPolicyError("same_card_host_required")
    if path and parsed.path != path:
        raise TestPolicyError("unexpected_path")
    if test_endpoint and not re.fullmatch(r"/localmark-test/[a-z0-9][a-z0-9_/-]{0,99}", parsed.path):
        raise TestPolicyError("dedicated_test_path_required")
    return host, parsed.path or "/"


def advertised_manifest(card, card_url):
    host, _ = _url(card_url)
    if urlsplit(card_url).path not in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
        raise TestPolicyError("well_known_card_required")
    capabilities = card.get("capabilities") if isinstance(card, dict) else None
    extensions = capabilities.get("extensions", []) if isinstance(capabilities, dict) else []
    if not isinstance(extensions, list):
        raise TestPolicyError("not_opted_in")
    matches = [item for item in extensions if isinstance(item, dict) and item.get("uri") == EXTENSION_URI]
    if len(matches) != 1:
        raise TestPolicyError("not_opted_in")
    params = matches[0].get("params")
    url = params.get("manifestUrl") if isinstance(params, dict) else None
    _url(url, same_host=host, path=MANIFEST_PATH)
    return url


def validate_manifest(manifest, card_url, now=None):
    now = now or utcnow()
    host, _ = _url(card_url)
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1 or manifest.get("agent_card_url") != card_url):
        raise TestPolicyError("invalid_manifest_identity")
    consent = manifest.get("consent")
    if (not isinstance(consent, dict) or consent.get("operator") != "LocalMark"
            or consent.get("purpose") != "synthetic_capability_tests"
            or consent.get("cost") != "free" or consent.get("dedicated_test_endpoints") is not True):
        raise TestPolicyError("explicit_free_test_consent_required")
    quota = consent.get("max_requests_per_day")
    if type(quota) is not int or not 1 <= quota <= 3:
        raise TestPolicyError("invalid_daily_quota")
    try:
        expiry = datetime.fromisoformat(consent["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or not now < expiry <= now + timedelta(days=90):
            raise TestPolicyError("consent_expired_or_too_long")
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        if isinstance(exc, TestPolicyError):
            raise
        raise TestPolicyError("invalid_consent_expiry") from exc
    tests = manifest.get("tests")
    if not isinstance(tests, list) or not 1 <= len(tests) <= min(3, quota):
        raise TestPolicyError("invalid_test_count")
    seen = set()
    clean = []
    for entry in tests:
        if (not isinstance(entry, dict) or not isinstance(entry.get("kind"), str) or entry["kind"] not in FIXTURES
                or not isinstance(entry.get("id"), str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,59}", entry["id"])
                or entry["id"] in seen or set(entry) - {"id", "kind", "url"}):
            raise TestPolicyError("invalid_test_entry")
        _url(entry.get("url"), same_host=host, test_endpoint=True)
        seen.add(entry["id"])
        clean.append({key: entry[key] for key in ("id", "kind", "url")})
    return {"host": host, "expires_at": expiry, "quota": quota, "tests": clean}


class _HeaderLimitedFile:
    def __init__(self, raw):
        self.raw = raw
        self.header_bytes = 0
        self.headers = True

    def readline(self, limit=-1):
        value = self.raw.readline(min(8193, limit) if limit > 0 else 8193)
        if self.headers:
            self.header_bytes += len(value)
            if self.header_bytes > 8192:
                raise TestPolicyError("response_headers_too_large")
            if value in (b"\r\n", b"\n"):
                self.headers = False
        return value

    def __getattr__(self, name):
        return getattr(self.raw, name)


class _ResponseSocket:
    def __init__(self, secure):
        self.secure = secure

    def makefile(self, mode):
        return _HeaderLimitedFile(self.secure.makefile(mode))


def pinned_json_request(url, method="GET", payload=None, *, max_bytes=32768):
    """DNS-pin one TLS connection; no redirects, proxy, cookies, auth, retries, or payments.

    POST uses exactly one connection, including when the response is lost. A hard
    wall-clock timer bounds slow headers and bodies as well as socket timeouts.
    """
    host, path = _url(url)
    if method not in ("GET", "POST") or (method == "POST" and payload is None):
        raise TestPolicyError("unsupported_request")
    _url(url, test_endpoint=method == "POST")
    addresses = _resolve(host)
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise TestPolicyError("nonpublic_dns")
    ip = sorted(addresses, key=lambda item: (":" in item, item))[0]
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8") if payload is not None else b""
    if len(body) > 8192:
        raise TestPolicyError("request_too_large")
    headers = (f"{method} {path} HTTP/1.1\r\nHost: {host}\r\n"
               "Accept: application/json\r\nAccept-Encoding: identity\r\n"
               "User-Agent: LocalMarkSyntheticTest/1 (+https://localmark.ai/capability-tests)\r\n"
               "Connection: close\r\n")
    if body:
        headers += f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
    raw = None
    secure = None
    response = None

    def abort():
        target = secure or raw
        if target is not None:
            try:
                target.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            target.close()

    timer = threading.Timer(10, abort)
    timer.daemon = True
    timer.start()
    try:
        raw = socket.create_connection((ip, 443), timeout=4)
        raw.settimeout(4)
        secure = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        secure.settimeout(4)
        secure.sendall((headers + "\r\n").encode("ascii") + body)
        response = http.client.HTTPResponse(_ResponseSocket(secure))
        response.begin()
        if response.status != 200:
            raise TestPolicyError(f"http_{response.status}")
        if response.getheader("Content-Type", "").split(";")[0].strip().lower() not in ("application/json", "application/agent+json", "application/a2a+json"):
            raise TestPolicyError("non_json_response")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise TestPolicyError("encoded_response_not_supported")
        value = response.read(max_bytes + 1)
        if len(value) > max_bytes:
            raise TestPolicyError("response_too_large")
        result = json.loads(value)
        if not isinstance(result, dict):
            raise TestPolicyError("json_object_required")
        return result
    finally:
        timer.cancel()
        if response:
            response.close()
        if secure:
            secure.close()
        elif raw:
            raw.close()


def _resolve(host):
    result = queue.Queue(maxsize=1)

    def resolve():
        try:
            result.put({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        except OSError as exc:
            result.put(exc)

    thread = threading.Thread(target=resolve, daemon=True)
    thread.start()
    try:
        value = result.get(timeout=4)
    except queue.Empty as exc:
        raise TestPolicyError("dns_timeout") from exc
    if isinstance(value, OSError):
        raise TestPolicyError("dns_failed") from value
    return value


def assert_result(kind, observed):
    assertion = fixture(kind)["assertion"]
    if assertion["type"] == "exact_json":
        # JSON booleans compare equal to 0/1 in Python; canonical JSON avoids that.
        return json.dumps(observed, sort_keys=True, allow_nan=False) == json.dumps(assertion["expected"], sort_keys=True)
    if not isinstance(observed, dict) or set(observed) != {"latitude", "longitude"}:
        return False
    return all(type(observed[key]) in (int, float) and math.isfinite(observed[key])
               and abs(observed[key] - assertion[key]) <= assertion["tolerance_degrees"]
               for key in ("latitude", "longitude"))


def run_authorized_tests(card_url, *, fetch=pinned_json_request, reserve=None, now=None):
    """Fetch fresh consent and run a fixed suite; reserve must persist before each POST."""
    now = now or utcnow()
    outcome = {"status": "not_tested", "reason_code": "not_opted_in", "results": []}
    try:
        _url(card_url)
        if urlsplit(card_url).path not in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
            raise TestPolicyError("well_known_card_required")
        fresh_card = fetch(card_url, "GET", max_bytes=262144)
        manifest_url = advertised_manifest(fresh_card, card_url)
        manifest = fetch(manifest_url, "GET")
        validated = validate_manifest(manifest, card_url, now)
        outcome["manifest_sha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        outcome["consent_expires_at"] = validated["expires_at"]
        if reserve is None:
            raise TestPolicyError("persistent_request_reservation_required")
        for entry in validated["tests"]:
            if not reserve(validated["host"], validated["quota"], entry):
                outcome["results"].append({**entry, "status": "not_tested", "reason_code": "daily_quota_reached"})
                continue
            row = {**entry, "fixture_version": FIXTURE_VERSION, "status": "failed", "reason_code": "assertion_failed"}
            try:
                observed = fetch(entry["url"], "POST", fixture(entry["kind"])["request"])
                row["response_sha256"] = hashlib.sha256(json.dumps(observed, sort_keys=True, allow_nan=False).encode()).hexdigest()
                if assert_result(entry["kind"], observed):
                    row.update(status="passed", reason_code="assertion_passed")
            except (OSError, ValueError, RecursionError, http.client.HTTPException) as exc:
                row["reason_code"] = str(exc) if isinstance(exc, TestPolicyError) else "request_failed"
            outcome["results"].append(row)
        statuses = [row["status"] for row in outcome["results"]]
        outcome["status"] = "passed" if statuses and all(s == "passed" for s in statuses) else "failed" if "failed" in statuses else "not_tested"
        outcome["reason_code"] = "suite_passed" if outcome["status"] == "passed" else "suite_failed" if outcome["status"] == "failed" else "daily_quota_reached"
    except (OSError, ValueError, RecursionError, http.client.HTTPException) as exc:
        outcome["reason_code"] = str(exc) if isinstance(exc, TestPolicyError) else "consent_fetch_failed"
    return outcome


def _reserve_request(conn, agent_id, host, quota, entry):
    """Atomically count every attempted request in a rolling 24 hours, including failures."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("capability-test:" + host,))
        row = conn.execute("""SELECT count(*) FILTER (WHERE host=%s), count(*) FILTER (WHERE agent_id=%s)
            FROM capability_test_requests WHERE requested_at > now()-interval '24 hours'
            AND (host=%s OR agent_id=%s)""", (host, agent_id, host, agent_id)).fetchone()
        if row[0] >= min(3, quota) or row[1] >= quota:
            return False
        conn.execute("INSERT INTO capability_test_requests(agent_id,host,test_id,endpoint) VALUES (%s,%s,%s,%s)",
                     (agent_id, host, entry["id"], entry["url"]))
    return True


def run_cycle(database_url=None, max_agents=10):
    import psycopg
    from psycopg.types.json import Jsonb
    database_url = database_url or DATABASE_URL or os.environ["DATABASE_URL"]
    count = 0
    with psycopg.connect(database_url, autocommit=True) as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(1876201201)").fetchone()[0]:
            return {"checked": 0, "state": "already_running"}
        try:
            rows = conn.execute(f"""SELECT a.id,a.card_url FROM agents a WHERE {PUBLIC_WHERE}
                AND (EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(a.card#>'{{capabilities,extensions}}')='array'
                    THEN a.card#>'{{capabilities,extensions}}' ELSE '[]'::jsonb END) e WHERE e->>'uri'=%s)
                    OR EXISTS (SELECT 1 FROM capability_test_runs prior WHERE prior.agent_id=a.id))
                AND NOT EXISTS (SELECT 1 FROM capability_test_runs r WHERE r.agent_id=a.id AND r.checked_at>now()-interval '24 hours')
                ORDER BY (SELECT max(checked_at) FROM capability_test_runs r WHERE r.agent_id=a.id) ASC NULLS FIRST,a.id LIMIT %s""",
                (EXTENSION_URI, min(50, max(1, max_agents)))).fetchall()
            for agent_id, card_url in rows:
                # Re-read public eligibility immediately before any consent fetch.
                if not conn.execute(f"SELECT 1 FROM agents a WHERE a.id=%s AND {PUBLIC_WHERE}", (agent_id,)).fetchone():
                    continue
                result = run_authorized_tests(card_url, reserve=lambda host, quota, entry: _reserve_request(conn, agent_id, host, quota, entry))
                conn.execute("""INSERT INTO capability_test_runs(agent_id,card_url,status,reason_code,manifest_sha256,consent_expires_at,results)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""", (agent_id, card_url, result["status"], result["reason_code"],
                    result.get("manifest_sha256"), result.get("consent_expires_at"), Jsonb(result["results"])))
                count += 1
            conn.execute("""INSERT INTO service_runs(service,finished_at,detail) VALUES ('capability_tests',now(),%s)
                ON CONFLICT(service) DO UPDATE SET finished_at=excluded.finished_at,detail=excluded.detail""", (f"{count} opted-in agents checked; no paid or production tasks sent",))
        finally:
            conn.execute("SELECT pg_advisory_unlock(1876201201)")
    return {"checked": count, "state": "complete"}


def current_assessment(current_card, card_url, latest, now=None):
    """Separate dated history from present consent and freshness evidence."""
    now = now or utcnow()
    result = {"status": "not_tested", "reason_code": "not_yet_tested", "consent_status": "not_confirmed"}
    if latest:
        result["reason_code"] = latest["reason_code"]
        try:
            advertised_manifest(current_card, card_url)
            if latest["consent_expires_at"] and latest["consent_expires_at"] <= now:
                result.update(consent_status="expired", reason_code="consent_expired")
            elif latest["checked_at"] < now - timedelta(hours=48):
                result.update(consent_status="not_recently_checked", reason_code="observation_stale")
            else:
                result.update(status=latest["status"], consent_status="active_at_last_check" if latest["consent_expires_at"] else "not_confirmed")
        except TestPolicyError:
            result.update(consent_status="not_currently_advertised", reason_code="not_opted_in")
    return result


def evidence_scope(card_url):
    """LocalMark's own endpoint is a controlled plumbing demonstration, not independent evidence."""
    try:
        host, _ = _url(card_url)
        reference = host == "localmark.ai"
    except TestPolicyError:
        reference = False
    return {"reference_demonstration": reference,
            "scope": ("LocalMark-controlled reference fixture demonstration. This tests the reporting plumbing only; "
                      "it is not an independent capability evaluation. " + SCOPE) if reference else SCOPE}


def public_results(agent_id):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(DATABASE_URL or os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        agent = conn.execute(f"""SELECT a.id,a.name,a.card_url,a.card FROM agents a WHERE {PUBLIC_WHERE}
            AND a.id=COALESCE((SELECT canonical_agent_id FROM agent_aliases WHERE alias_agent_id=%s),%s)""", (agent_id, agent_id)).fetchone()
        if not agent:
            return None
        rows = conn.execute("""SELECT checked_at,status,reason_code,manifest_sha256,consent_expires_at,results
            FROM capability_test_runs WHERE agent_id=%s OR agent_id IN
                (SELECT alias_agent_id FROM agent_aliases WHERE canonical_agent_id=%s)
            ORDER BY checked_at DESC,id DESC LIMIT 10""", (agent["id"], agent["id"])).fetchall()
    current = current_assessment(agent["card"], agent["card_url"], rows[0] if rows else None)
    return {"agent_id": agent["id"], **current,
            "latest_observation_status": rows[0]["status"] if rows else None,
            "last_checked_at": rows[0]["checked_at"] if rows else None,
            "fixture_version": FIXTURE_VERSION, **evidence_scope(agent["card_url"]),
            "methodology_url": "https://localmark.ai/capability-tests", "history": rows}


def build_router():
    from fastapi import APIRouter, HTTPException
    router = APIRouter()

    @router.get("/api/v1/agents/{agent_id}/capability-tests")
    def agent_capability_tests(agent_id: int):
        result = public_results(agent_id)
        if result is None:
            raise HTTPException(404, "Agent not found")
        return result

    @router.get("/api/v1/capability-test-fixtures")
    def capability_test_fixtures():
        return {"fixture_version": FIXTURE_VERSION, "scope": SCOPE, "fixtures": FIXTURES}

    return router


def make_demo_manifest(card_url, expires_at=None):
    host, _ = _url(card_url)
    expiry = expires_at or utcnow() + timedelta(days=60)
    return {"schema_version": 1, "agent_card_url": card_url,
            "consent": {"operator": "LocalMark", "purpose": "synthetic_capability_tests", "cost": "free",
                        "dedicated_test_endpoints": True, "expires_at": expiry.isoformat(), "max_requests_per_day": 3},
            "tests": [{"id": kind.replace("_", "-") + "-v1", "kind": kind,
                       "url": f"https://{host}/localmark-test/{kind.replace('_', '-')}"} for kind in FIXTURES]}


def demo_response(kind, payload):
    """Controlled reference implementation only. Never use this as third-party evidence."""
    if payload != fixture(kind)["request"]:
        raise TestPolicyError("unknown_reference_fixture")
    if kind == "json_transform":
        rows = payload["input"]["rows"]
        return {"output": {"ids": sorted((row["id"] for row in rows), reverse=True), "total": sum(row["quantity"] for row in rows)}}
    if kind == "geocoding":
        return {"latitude": 38.7223, "longitude": -9.1393}
    # Fixed expected text is explicit: this demo is a plumbing demonstration,
    # not an assertion that LocalMark is a production PDF extraction provider.
    return {"text": "LocalMark synthetic invoice\nInvoice LM-TEST-0042\nTotal EUR 12.50"}


def instruction_html():
    card = {"capabilities": {"extensions": [{"uri": EXTENSION_URI, "params": {"manifestUrl": "https://your-agent.example/.well-known/localmark-tests.json"}}]}}
    manifest = make_demo_manifest("https://your-agent.example/.well-known/agent-card.json")
    examples = "".join(f"<details><summary>{escape(kind.replace('_', ' ').title())}</summary><p>{escape(value['scope'])}</p>"
                       f"<h3>Exact request</h3><pre>{escape(json.dumps(value['request'],indent=2))}</pre>"
                       f"<h3>Assertion</h3><pre>{escape(json.dumps(value['assertion'],indent=2))}</pre></details>" for kind, value in FIXTURES.items())
    return ("<section class='section'><p class='eyebrow'>Publisher opt-in</p><h1>Reproducible capability tests</h1>"
            f"<p>{escape(SCOPE)}</p><p>These are three small, fully published fixtures. A passing endpoint can be tailored to them; "
            "the result is evidence about that fixture, not a quality certification. LocalMark's reference endpoints demonstrate the plumbing only.</p>"
            "<h2>What we send</h2><p>Only the synthetic request shown below, with no user data, account keys, payment, external tools, or production A2A task. "
            "A test endpoint must be on the exact card host under <code>/localmark-test/</code> and return JSON.</p>"
            "<h2>How to opt in</h2><ol><li>Add the extension below to your live Agent Card.</li>"
            "<li>Serve the consent manifest at the same host's well-known path. Replace the example URLs and choose an expiry no more than 90 days away.</li>"
            "<li>Implement only the fixtures you choose on dedicated free endpoints. Every listed test consumes one request.</li></ol>"
            f"<pre>{escape(json.dumps(card,indent=2))}</pre><pre>{escape(json.dumps(manifest,indent=2))}</pre>"
            "<h2>Limits and withdrawal</h2><p>At most three POST attempts per host and agent in any rolling 24 hours, including failed requests; "
            "you can lower that limit. Each response is bounded to 32 KiB and each connection to 10 seconds. "
            "Redirects, credentials, private network addresses, paid endpoints and arbitrary request bodies are refused.</p>"
            "<p>Remove the extension, remove the manifest, or expire its consent to stop future tests. The live card and manifest are fetched again before each daily cycle. "
            "Previously published observations remain dated history; they do not mean consent is still active.</p>"
            "<p>Failure does not remove your listing. Network errors and unexpected output are reported separately, and no result is a statement about safety or identity.</p>"
            f"<h2>Public fixtures, version {FIXTURE_VERSION}</h2>{examples}"
            "<p><a href='/api/v1/capability-test-fixtures'>Download the exact requests and assertions as JSON</a>. "
            "Each agent's public results are at <code>/api/v1/agents/{id}/capability-tests</code>.</p></section>")
