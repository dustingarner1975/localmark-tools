# Publisher-authorized synthetic capability tests, version 1

These tests exercise a **dedicated free test endpoint** only when the live Agent Card advertises explicit consent. They are separate from normal card fetches, TLS checks and read-only A2A protocol probes. They do not submit production A2A tasks.

A result is dated evidence about one published fixture. It does not establish general capability, identity, safety, uptime or production task success. Since the fixtures are public and fixed, an endpoint can be tailored to them. LocalMark's own reference endpoints demonstrate the plumbing; their results are not independent evaluations.

## Opt in

Add this extension to the live Agent Card's `capabilities.extensions` array:

```json
{
  "uri": "https://localmark.ai/extensions/capability-tests/v1",
  "params": {
    "manifestUrl": "https://agent.example/.well-known/localmark-tests.json"
  }
}
```

Serve this manifest on the **exact same hostname** as the Agent Card. Replace the example URLs and choose an explicit timezone-aware expiry no more than 90 days away. Select only the tests your dedicated endpoints implement.

```json
{
  "schema_version": 1,
  "agent_card_url": "https://agent.example/.well-known/agent-card.json",
  "consent": {
    "operator": "LocalMark",
    "purpose": "synthetic_capability_tests",
    "cost": "free",
    "dedicated_test_endpoints": true,
    "expires_at": "2026-11-19T12:00:00+00:00",
    "max_requests_per_day": 1
  },
  "tests": [
    {
      "id": "json-transform-v1",
      "kind": "json_transform",
      "url": "https://agent.example/localmark-test/json-transform"
    }
  ]
}
```

The endpoint accepts the exact JSON request in `/api/v1/capability-test-fixtures` and returns the expected JSON document with HTTP 200 and a JSON content type. There are no publisher-defined inputs, arbitrary assertions, callbacks, credentials, payment headers or remote tools. Only the three versioned LocalMark fixtures are supported.

### Fixtures

| Kind | Request | Assertion | Limit |
| --- | --- | --- | --- |
| `json_transform` | Two synthetic rows, IDs LM-001 / LM-002 and quantities 2 / 3 | Exactly `{"output":{"ids":["LM-002","LM-001"],"total":5}}` | One sorting/arithmetic example |
| `pdf_extraction` | One synthetic single-page text PDF supplied as base64 | Exact three-line text | No scans, OCR, complex layout or real documents |
| `geocoding` | Lisbon, Portugal | Numeric latitude 38.7223, longitude -9.1393, each within 0.15 degrees | City-level public place only |

The complete PDF bytes, request bodies, expected responses and assertions are published at `/api/v1/capability-test-fixtures` and on `/capability-tests`. The fixture version is included in every test result.

## Controls

- Consent is fetched from the **live** Agent Card and same-host manifest before every cycle, not accepted from a registry copy alone.
- Test URLs must use public HTTPS on port 443, the exact card hostname, and a dedicated `/localmark-test/` path. Queries, fragments, credentials, IP literal hosts, encoded path escapes and redirects are refused.
- Every DNS answer must be public. The request connects to a pinned answer while validating the original hostname's TLS certificate. A second DNS lookup cannot redirect the connection internally.
- At most three POST attempts per hostname and agent in a rolling 24 hours, including failures. A publisher can set a smaller limit. Reservations are persisted **before** dispatch and serialized per host, so concurrent runners and restarts do not reset the allowance.
- One POST connection per test; no retries after a lost response. No payments or authentication are attempted, including for HTTP 401 or 402 responses.
- DNS resolution has a four-second wait bound. Connections, headers and bodies have a ten-second absolute deadline and four-second socket timeout; response headers are at most 8 KiB, JSON responses at most 32 KiB and request bodies at most 8 KiB. The fresh Agent Card alone may be at most 256 KiB.
- No raw response content is retained. Public evidence includes the fixed fixture version, test URL, result, bounded reason code, response SHA-256, manifest SHA-256, consent expiry and timestamp.
- Failed tests **do not reject or hide listings** and do not automatically become a global quality score.

## Withdraw consent

Remove the extension or manifest, or let consent expire. The next daily cycle re-fetches both and sends no further POST after withdrawal is observed. Removal is not immediate during an already running cycle. Historical dated observations remain visible, with their consent expiry; they are not a statement that consent remains active.

## Public results

`GET /api/v1/agents/{id}/capability-tests` returns up to ten recent cycles and the test scope. Public aliases resolve to the canonical agent and retain results from their alternate addresses. Hidden and restricted agents are excluded.

In history, `passed` means every selected fixture assertion passed that cycle. `failed` means at least one attempted request failed or returned unexpected output. `not_tested` means consent was missing, expired or invalid, or no request was permitted by the rolling quota. Individual results have separate reason codes such as `assertion_failed`, `request_failed`, `http_402`, `not_opted_in` and `daily_quota_reached`.

The top-level current status becomes `not_tested` if the latest stored live card no longer advertises consent, the recorded consent has expired, or the latest observation is more than 48 hours old. `latest_observation_status` and the dated history remain available, so an old pass cannot silently appear current after a known withdrawal or expiry. The API never performs a test or makes an outbound request just to answer a read.

`consent_status: active_at_last_check` is intentionally limited to the most recent observation. It does not assert that the publisher has not since withdrawn consent.

## Integration

1. Append `capability_tests.SCHEMA` to API schema creation. Schema creation is idempotent.
2. Call `capability_tests.configure(DATABASE_URL, PUBLIC_WHERE)` and mount `capability_tests.build_router()`.
3. Render `capability_tests.instruction_html()` with the site shell for `/capability-tests`.
4. Include the same `capability_tests.py` module in the worker image. Run `python capability_test_runner.py` as a bounded, read-only-filesystem service with database access and restart policy. It polls hourly and only tests agents due after 24 hours.
5. The worker records a `service_runs` heartbeat named `capability_tests` for the existing system-health UI.

No third-party endpoint is contacted merely because this code is installed. A fresh live card, valid explicit consent and persistent request reservation are all required before a POST.
