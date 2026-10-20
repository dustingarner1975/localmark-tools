import unittest
import io
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError

from localmark_client import LocalMarkClient
from localmark_client.client import LocalMarkError
from localmark_client.cli import main


class ClientTests(unittest.TestCase):
    def test_gate_requires_fresh_evidence(self):
        now = datetime.now(timezone.utc).isoformat()
        evidence = {"listing_status": "listed",
                    "card_reachability": {"latest": {"success": True, "checked_at": now}},
                    "read_only_a2a_probe": {"state": "a2a_response", "checked_at": now},
                    "endpoint_tls": {"success": True, "checked_at": now}}
        client = LocalMarkClient()
        with patch.object(client, "verify", return_value=evidence):
            self.assertTrue(client.gate("agent.example", a2a_hours=24, tls=True)["passed"])
            self.assertFalse(client.gate("agent.example", signature=True)["passed"])
        evidence["read_only_a2a_probe"]["checked_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with patch.object(client, "verify", return_value=evidence):
            self.assertFalse(client.gate("agent.example", a2a_hours=24)["passed"])

    def test_unseen_agent_fails_closed(self):
        client = LocalMarkClient()
        with patch.object(client, "verify", return_value={"listing_status": "not_seen"}):
            self.assertFalse(client.gate("unknown.example/a2a")["passed"])

    def test_recommend_serializes_requirements_and_preserves_ranking(self):
        ranked = {"items": [{"id": 7, "recommendation": {"reasons": ["PDF skill match"],
                    "caveats": ["Task performance not tested"]}}],
                  "total_matches": 1, "ranking_version": "capability-v1"}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(ranked).encode()
        with patch("localmark_client.client.urlopen", return_value=response) as request:
            result = LocalMarkClient().recommend(" PDF forms ", auth="none", signature="verified",
                protocol="HTTP+JSON", checked_within_hours=24, a2a_response_within_hours=12,
                tls_reachable=False, network="eip155:8453", asset="0xUSDC", max_amount="0.05",
                limit=5, offset=10)
        self.assertEqual(result, ranked)
        sent = request.call_args.args[0]
        self.assertEqual(urlsplit(sent.full_url).path, "/api/v1/recommend")
        self.assertEqual(parse_qs(urlsplit(sent.full_url).query), {
            "q": ["PDF forms"], "auth": ["none"], "signature": ["verified"],
            "protocol": ["HTTP+JSON"], "checked_within_hours": ["24"],
            "a2a_response_within_hours": ["12"], "tls_reachable": ["false"],
            "network": ["eip155:8453"], "asset": ["0xUSDC"], "max_amount": ["0.05"],
            "limit": ["5"], "offset": ["10"],
        })
        self.assertEqual(sent.get_header("User-agent"), "localmark-client/0.4.1")

    def test_recommend_rejects_invalid_requirements_before_request(self):
        client = LocalMarkClient()
        cases = [{"q": ""}, {"q": "x" * 201}, {"auth": "free"},
                 {"signature": True}, {"protocol": "MCP"}, {"limit": 21},
                 {"offset": -1}, {"checked_within_hours": 169},
                 {"a2a_response_within_hours": 0}, {"tls_reachable": "true"},
                 {"max_amount": "0.05"},
                 *[{"max_amount": value, "asset": "USDC", "network": "eip155:8453"}
                   for value in ("-1", "nan", "Infinity", "oops", "1e999999999", "1" * 101)]]
        with patch.object(client, "_get") as request:
            for case in cases:
                with self.subTest(case=case), self.assertRaises(ValueError):
                    args = {"q": "PDF", **case}
                    client.recommend(**args)
            request.assert_not_called()

    def test_recommend_http_error_keeps_retry_after(self):
        error = HTTPError("https://localmark.ai/api/v1/recommend", 429, "Too many requests",
                          {"Retry-After": "60"}, io.BytesIO(b'{"detail":"Slow down"}'))
        with patch("localmark_client.client.urlopen", side_effect=error):
            with self.assertRaises(LocalMarkError) as raised:
                LocalMarkClient().recommend("weather")
        self.assertEqual(raised.exception.status, 429)
        self.assertEqual(raised.exception.retry_after, "60")
        self.assertIn("Slow down", str(raised.exception))

    def test_recommend_cli_forwards_filters_and_prints_structured_result(self):
        result = {"items": [], "total_matches": 0, "ranking_version": "capability-v1"}
        with patch("localmark_client.cli.LocalMarkClient") as constructor, patch("sys.stdout", new_callable=io.StringIO) as output:
            constructor.return_value.recommend.return_value = result
            code = main(["recommend", "PDF forms", "--auth", "none", "--signature", "verified",
                         "--protocol", "JSONRPC", "--card-hours", "24", "--a2a-hours", "12",
                         "--tls", "--network", "eip155:8453", "--asset", "USDC",
                         "--max-amount", "0.05", "--limit", "3", "--offset", "6"])
            constructor.return_value.recommend.assert_called_once_with("PDF forms", policy=None, auth="none",
                signature="verified", protocol="JSONRPC", checked_within_hours=24,
                a2a_response_within_hours=12, tls_reachable=True, network="eip155:8453",
                asset="USDC", max_amount="0.05", limit=3, offset=6)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), result)

    def test_recommend_cli_reports_requirement_error(self):
        with patch("localmark_client.cli.LocalMarkClient") as constructor, patch("sys.stderr", new_callable=io.StringIO) as errors:
            constructor.return_value.recommend.side_effect = ValueError("max_amount requires both network and asset")
            code = main(["recommend", "weather", "--max-amount", "0.05"])
        self.assertEqual(code, 1)
        self.assertIn("requires both network and asset", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
