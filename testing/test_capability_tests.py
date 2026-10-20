import copy
import json
import io
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import capability_tests as ct


NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
CARD_URL = "https://agent.example/.well-known/agent-card.json"
MANIFEST_URL = "https://agent.example/.well-known/localmark-tests.json"


def manifest():
    return ct.make_demo_manifest(CARD_URL, NOW + timedelta(days=30))


def card():
    return {"capabilities": {"extensions": [{"uri": ct.EXTENSION_URI, "params": {"manifestUrl": MANIFEST_URL}}]}}


class TestConsent(unittest.TestCase):
    def test_advertised_manifest_exact_host_and_path(self):
        self.assertEqual(ct.advertised_manifest(card(), CARD_URL), MANIFEST_URL)
        value = card()
        value["capabilities"]["extensions"][0]["params"]["manifestUrl"] = "https://other.example/.well-known/localmark-tests.json"
        with self.assertRaises(ct.TestPolicyError):
            ct.advertised_manifest(value, CARD_URL)

    def test_missing_or_duplicate_extension_is_not_opt_in(self):
        for value in ({}, {"capabilities": {"extensions": []}}, {"capabilities": {"extensions": card()["capabilities"]["extensions"] * 2}}):
            with self.subTest(card=value), self.assertRaises(ct.TestPolicyError):
                ct.advertised_manifest(value, CARD_URL)

    def test_valid_free_manifest(self):
        value = ct.validate_manifest(manifest(), CARD_URL, NOW)
        self.assertEqual(value["quota"], 3)
        self.assertEqual(len(value["tests"]), 3)

    def test_expiry_required_bounded_and_timezone_aware(self):
        for expiry in (NOW.isoformat(), (NOW - timedelta(seconds=1)).isoformat(),
                       (NOW + timedelta(days=91)).isoformat(), "2026-10-25T00:00:00", None, "bad"):
            value = manifest()
            value["consent"]["expires_at"] = expiry
            with self.subTest(expiry=expiry), self.assertRaises(ct.TestPolicyError):
                ct.validate_manifest(value, CARD_URL, NOW)

    def test_each_explicit_consent_field_required(self):
        for key in ("operator", "purpose", "cost", "dedicated_test_endpoints"):
            value = manifest()
            value["consent"].pop(key)
            with self.subTest(key=key), self.assertRaises(ct.TestPolicyError):
                ct.validate_manifest(value, CARD_URL, NOW)

    def test_manifest_cannot_authorize_other_card(self):
        value = manifest()
        value["agent_card_url"] = "https://agent.example/.well-known/agent.json"
        with self.assertRaises(ct.TestPolicyError):
            ct.validate_manifest(value, CARD_URL, NOW)

    def test_quota_integer_and_test_count_bounded(self):
        for quota in (0, 4, True, "3", 1):
            value = manifest()
            value["consent"]["max_requests_per_day"] = quota
            with self.subTest(quota=quota), self.assertRaises(ct.TestPolicyError):
                ct.validate_manifest(value, CARD_URL, NOW)

    def test_dedicated_same_host_test_paths_only(self):
        for endpoint in ("https://other.example/localmark-test/pdf", "http://agent.example/localmark-test/pdf",
                         "https://agent.example:8443/localmark-test/pdf", "https://agent.example/a2a",
                         "https://agent.example/localmark-test/%2e%2e/a2a", "https://agent.example/localmark-test/pdf?pay=1",
                         "https://user:pass@agent.example/localmark-test/pdf", "https://127.0.0.1/localmark-test/pdf"):
            value = manifest()
            value["tests"][0]["url"] = endpoint
            with self.subTest(endpoint=endpoint), self.assertRaises(ct.TestPolicyError):
                ct.validate_manifest(value, CARD_URL, NOW)

    def test_arbitrary_input_or_duplicate_id_refused(self):
        value = manifest()
        value["tests"][0]["input"] = {"run": "something"}
        with self.assertRaises(ct.TestPolicyError):
            ct.validate_manifest(value, CARD_URL, NOW)
        value = manifest()
        value["tests"][1]["id"] = value["tests"][0]["id"]
        with self.assertRaises(ct.TestPolicyError):
            ct.validate_manifest(value, CARD_URL, NOW)


class TestExecution(unittest.TestCase):
    def fetcher(self, *, current_card=None, current_manifest=None, wrong=False, error=None):
        def fetch(url, method="GET", payload=None, **kwargs):
            if url == CARD_URL:
                return current_card if current_card is not None else card()
            if url == MANIFEST_URL:
                return current_manifest if current_manifest is not None else manifest()
            if error:
                raise error
            return {"wrong": True} if wrong else ct.demo_response(payload["kind"], payload)
        return Mock(side_effect=fetch)

    def test_full_suite_fixed_requests_and_public_hashes(self):
        fetch = self.fetcher()
        reserve = Mock(return_value=True)
        result = ct.run_authorized_tests(CARD_URL, fetch=fetch, reserve=reserve, now=NOW)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(reserve.call_count, 3)
        self.assertEqual(len(fetch.call_args_list), 5)
        self.assertTrue(all(row["response_sha256"] for row in result["results"]))
        for call in fetch.call_args_list[2:]:
            self.assertEqual(call.args[1], "POST")
            self.assertEqual(call.args[2], ct.fixture(call.args[2]["kind"])["request"])
        self.assertTrue(all("response" not in row and "output" not in row for row in result["results"]))

    def test_revoked_extension_sends_no_manifest_or_post(self):
        fetch = self.fetcher(current_card={})
        result = ct.run_authorized_tests(CARD_URL, fetch=fetch, reserve=Mock(), now=NOW)
        self.assertEqual(result["reason_code"], "not_opted_in")
        self.assertEqual(fetch.call_count, 1)

    def test_expired_consent_sends_no_post(self):
        value = manifest()
        value["consent"]["expires_at"] = (NOW - timedelta(days=1)).isoformat()
        fetch = self.fetcher(current_manifest=value)
        result = ct.run_authorized_tests(CARD_URL, fetch=fetch, reserve=Mock(), now=NOW)
        self.assertEqual(result["status"], "not_tested")
        self.assertEqual(fetch.call_count, 2)

    def test_no_persistent_reservation_no_post(self):
        fetch = self.fetcher()
        result = ct.run_authorized_tests(CARD_URL, fetch=fetch, now=NOW)
        self.assertEqual(result["reason_code"], "persistent_request_reservation_required")
        self.assertEqual(fetch.call_count, 2)

    def test_quota_reached_does_not_dispatch(self):
        fetch = self.fetcher()
        result = ct.run_authorized_tests(CARD_URL, fetch=fetch, reserve=Mock(return_value=False), now=NOW)
        self.assertEqual(result["reason_code"], "daily_quota_reached")
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all(row["status"] == "not_tested" for row in result["results"]))

    def test_failed_assertion_is_dated_failure_not_rejection(self):
        fetch = self.fetcher(wrong=True)
        result = ct.run_authorized_tests(CARD_URL, fetch=fetch, reserve=Mock(return_value=True), now=NOW)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(all(row["reason_code"] == "assertion_failed" for row in result["results"]))

    def test_network_failure_consumes_reservation_and_no_retry(self):
        fetch = self.fetcher(error=OSError("private error that must not be public"))
        reserve = Mock(return_value=True)
        result = ct.run_authorized_tests(CARD_URL, fetch=fetch, reserve=reserve, now=NOW)
        self.assertEqual(reserve.call_count, 3)
        self.assertEqual(fetch.call_count, 5)
        self.assertTrue(all(row["reason_code"] == "request_failed" for row in result["results"]))
        self.assertNotIn("private error", json.dumps(result, default=str))

    def test_boolean_total_cannot_pass_arithmetic(self):
        self.assertFalse(ct.assert_result("json_transform", {"output": {"ids": ["LM-002", "LM-001"], "total": True}}))

    def test_coordinate_assertion_numeric_finite_bounded(self):
        self.assertTrue(ct.assert_result("geocoding", {"latitude": 38.72, "longitude": -9.14}))
        for value in ({"latitude": 90, "longitude": -9}, {"latitude": float("nan"), "longitude": -9.1393},
                      {"latitude": "38.7223", "longitude": -9.1393}, {"latitude": 38.7223, "longitude": -9.1393, "extra": 1}):
            self.assertFalse(ct.assert_result("geocoding", value))

    def test_fixture_is_independent_valid_pdf(self):
        value = ct.fixture("json_transform")
        value["request"]["input"]["rows"].clear()
        self.assertEqual(len(ct.fixture("json_transform")["request"]["input"]["rows"]), 2)
        self.assertTrue(ct.base64.b64decode(ct.fixture("pdf_extraction")["request"]["input"]["pdf_base64"]).startswith(b"%PDF-1.4"))


class TestNetworkPolicy(unittest.TestCase):
    def test_private_or_mixed_dns_never_connects(self):
        for addresses in ({"127.0.0.1"}, {"8.8.8.8", "192.168.1.1"}, {"::1"}, set()):
            with self.subTest(addresses=addresses), patch.object(ct, "_resolve", return_value=addresses), patch.object(ct.socket, "create_connection") as connect:
                with self.assertRaisesRegex(ct.TestPolicyError, "nonpublic_dns"):
                    ct.pinned_json_request(MANIFEST_URL)
                connect.assert_not_called()

    def test_post_network_error_no_retry(self):
        with patch.object(ct, "_resolve", return_value={"8.8.8.8", "1.1.1.1"}), patch.object(ct.socket, "create_connection", side_effect=OSError("offline")) as connect:
            with self.assertRaises(OSError):
                ct.pinned_json_request("https://agent.example/localmark-test/json", "POST", {"test": 1})
            connect.assert_called_once()

    def test_redirect_and_payment_never_followed(self):
        for status in (301, 302, 307, 308, 401, 402):
            with self.subTest(status=status), patch.object(ct, "_resolve", return_value={"8.8.8.8"}), \
                    patch.object(ct.socket, "create_connection") as connect, \
                    patch.object(ct.ssl, "create_default_context") as ssl_context, \
                    patch.object(ct.http.client, "HTTPResponse") as response:
                response.return_value.status = status
                with self.assertRaisesRegex(ct.TestPolicyError, f"http_{status}"):
                    ct.pinned_json_request("https://agent.example/localmark-test/json", "POST", {"test": 1})
                connect.assert_called_once()
                ssl_context.return_value.wrap_socket.return_value.sendall.assert_called_once()

    def test_post_disallows_regular_a2a_endpoint(self):
        with patch.object(ct, "_resolve") as resolve:
            with self.assertRaises(ct.TestPolicyError):
                ct.pinned_json_request("https://agent.example/a2a", "POST", {})
            resolve.assert_not_called()

    def test_response_header_budget_is_enforced(self):
        wrapped = ct._HeaderLimitedFile(io.BytesIO(b"x" * 8193 + b"\r\n"))
        with self.assertRaisesRegex(ct.TestPolicyError, "response_headers_too_large"):
            wrapped.readline()

    def test_oversize_or_encoded_response_rejected(self):
        for content_type, encoding, body, reason in (
                ("application/json", "identity", b"x" * 32769, "response_too_large"),
                ("text/html", "identity", b"{}", "non_json_response"),
                ("application/json", "gzip", b"{}", "encoded_response_not_supported")):
            with self.subTest(reason=reason), patch.object(ct, "_resolve", return_value={"8.8.8.8"}), \
                    patch.object(ct.socket, "create_connection"), patch.object(ct.ssl, "create_default_context"), \
                    patch.object(ct.http.client, "HTTPResponse") as response:
                response.return_value.status = 200
                response.return_value.getheader.side_effect = lambda key, default=None: {"Content-Type": content_type, "Content-Encoding": encoding}.get(key, default)
                response.return_value.read.return_value = body
                with self.assertRaisesRegex(ct.TestPolicyError, reason):
                    ct.pinned_json_request(MANIFEST_URL)
                response.return_value.close.assert_called_once()

    def test_reservation_counts_host_and_agent_rolling_day(self):
        for counts, expected in (((0, 0), True), ((3, 0), False), ((0, 3), False), ((1, 0), False)):
            conn = Mock()
            conn.transaction.return_value.__enter__ = Mock()
            conn.transaction.return_value.__exit__ = Mock(return_value=False)
            conn.execute.return_value.fetchone.return_value = counts
            result = ct._reserve_request(conn, 7, "agent.example", 1, {"id": "test", "url": "https://agent.example/localmark-test/x"})
            self.assertEqual(result, expected)
            sql = " ".join(call.args[0] for call in conn.execute.call_args_list)
            self.assertIn("pg_advisory_xact_lock", sql)
            self.assertIn("interval '24 hours'", sql)
            self.assertEqual("INSERT INTO capability_test_requests" in sql, expected)


class TestCurrentEvidence(unittest.TestCase):
    def latest(self):
        return {"status": "passed", "reason_code": "suite_passed", "checked_at": NOW - timedelta(hours=1),
                "consent_expires_at": NOW + timedelta(days=1)}

    def test_previous_pass_is_not_current_after_optout(self):
        latest = self.latest()
        result = ct.current_assessment({}, CARD_URL, latest, NOW)
        self.assertEqual(result["status"], "not_tested")
        self.assertEqual(result["consent_status"], "not_currently_advertised")
        self.assertEqual(latest["status"], "passed")

    def test_expired_and_stale_pass_cannot_appear_current(self):
        latest = self.latest()
        latest["consent_expires_at"] = NOW
        self.assertEqual(ct.current_assessment(card(), CARD_URL, latest, NOW)["reason_code"], "consent_expired")
        latest = self.latest()
        latest["checked_at"] = NOW - timedelta(hours=49)
        self.assertEqual(ct.current_assessment(card(), CARD_URL, latest, NOW)["reason_code"], "observation_stale")

    def test_recent_observation_label_does_not_claim_present_consent(self):
        result = ct.current_assessment(card(), CARD_URL, self.latest(), NOW)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["consent_status"], "active_at_last_check")

    def test_own_reference_result_explicitly_disclaims_independent_evaluation(self):
        value = ct.evidence_scope("https://localmark.ai/.well-known/agent-card.json")
        self.assertTrue(value["reference_demonstration"])
        self.assertIn("reporting plumbing only", value["scope"])
        self.assertIn("not an independent capability evaluation", value["scope"])

    def test_other_host_or_invalid_lookalike_is_not_localmark_reference(self):
        for url in (CARD_URL, "https://localmark.ai.attacker.example/.well-known/agent-card.json",
                    "http://localmark.ai/.well-known/agent-card.json", "https://user:pass@localmark.ai/.well-known/agent-card.json"):
            with self.subTest(url=url):
                value = ct.evidence_scope(url)
                self.assertFalse(value["reference_demonstration"])
                self.assertEqual(value["scope"], ct.SCOPE)


if __name__ == "__main__":
    unittest.main()
