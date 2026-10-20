import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

from localmark_client import LocalMarkClient, load_policy, validate_policy
from localmark_client.cli import main

ACTION_PATH = Path(__file__).resolve().parents[1] / "action" / "run.py"
SPEC = importlib.util.spec_from_file_location("localmark_action_runner", ACTION_PATH)
action = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(action)


class IntegrationTests(unittest.TestCase):
    def test_policy_validates_without_mutating_and_applies_explicit_overrides(self):
        original = {"q": "PDF extraction", "checked_within_hours": 24, "tls_reachable": True,
                    "limit": 3}
        client = LocalMarkClient()
        with patch.object(client, "_get", return_value={"items": []}) as get:
            client.recommend(policy=original, checked_within_hours=12)
        self.assertEqual(original["checked_within_hours"], 24)
        self.assertEqual(get.call_args.args, ("/api/v1/recommend", {
            "q": "PDF extraction", "checked_within_hours": 12, "tls_reachable": "true",
            "limit": 3, "offset": 0}))

    def test_policy_rejects_unknown_secrets_nulls_and_invalid_types(self):
        for policy in ({"api_key": "secret"}, {"headers": {}}, {"endpoint": "https://x"},
                       {"q": None}, {"limit": True}, {"checked_within_hours": "24"},
                       {"tls_reachable": "true"}, {"max_amount": True, "network": "base", "asset": "USDC"},
                       {"offset": 100001}, {"auth": None}, {"network": "a\nb"}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                validate_policy(policy)

    def test_policy_file_rejects_duplicate_keys_oversize_and_bad_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "policy.json"
            for payload in ('{"q":"PDF","q":"weather"}', '{"q":NaN}', '[]', '{broken', ' ' * 65537):
                path.write_text(payload, encoding="utf-8")
                with self.subTest(payload=payload[:25]), self.assertRaises(ValueError):
                    load_policy(path)
            path.write_text('{"q":"PDF", "auth":"none"}', encoding="utf-8-sig")
            self.assertEqual(load_policy(path), {"q": "PDF", "auth": "none"})

    def test_recommend_cli_policy_query_optional_and_overridden(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "policy.json"
            path.write_text('{"q":"PDF", "limit":3, "tls_reachable":true}', encoding="utf-8")
            with patch("localmark_client.client.LocalMarkClient._get", return_value={"items": []}) as get, patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(main(["recommend", "--policy", str(path)]), 0)
                self.assertEqual(get.call_args.args[1]["q"], "PDF")
                self.assertEqual(get.call_args.args[1]["limit"], 3)
                self.assertEqual(main(["recommend", "weather", "--policy", str(path), "--limit", "5", "--no-tls"]), 0)
                self.assertEqual(get.call_args.args[1]["q"], "weather")
                self.assertEqual(get.call_args.args[1]["limit"], 5)
                self.assertEqual(get.call_args.args[1]["tls_reachable"], "false")

    def test_plan_only_calls_localmark_and_never_task_endpoint(self):
        client = LocalMarkClient()
        with patch.object(client, "_get", return_value={"requires_explicit_task_authorization": True}) as get:
            self.assertTrue(client.connection_plan(123)["requires_explicit_task_authorization"])
        get.assert_called_once_with("/api/v1/connection-plan", {"target": "123"})
        for target in ("", "a\r\nx", "x" * 2049):
            with self.assertRaises(ValueError):
                client.connection_plan(target)
        with patch("localmark_client.cli.LocalMarkClient") as constructor, patch("sys.stdout", new_callable=io.StringIO):
            constructor.return_value.connection_plan.return_value = {}
            self.assertEqual(main(["plan", "agent.example/a2a"]), 0)
            constructor.return_value.connection_plan.assert_called_once_with("agent.example/a2a")

    def test_cli_json_is_portable_to_windows_redirected_output(self):
        raw = io.BytesIO()
        output = io.TextIOWrapper(raw, encoding="cp1252")
        result = {"items": [{"name": "Agent ∈ 東京"}]}
        with patch("localmark_client.cli.LocalMarkClient") as constructor, patch("sys.stdout", output):
            constructor.return_value.recommend.return_value = result
            self.assertEqual(main(["recommend", "PDF"]), 0)
            output.flush()
            self.assertEqual(json.loads(raw.getvalue().decode("ascii")), result)

    def test_project_header_is_opt_in_and_rejects_non_random_identifiers(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        with patch("localmark_client.client.urlopen", return_value=response) as request:
            LocalMarkClient().health()
            self.assertIsNone(request.call_args.args[0].get_header("X-localmark-project"))
            identifier = "d8d8ae43-bdf5-4c1d-bcaf-66f92da5c9da"
            LocalMarkClient(project_id=identifier).health()
            self.assertEqual(request.call_args.args[0].get_header("X-localmark-project"), identifier)
        for identifier in ("secret", "00000000-0000-0000-0000-000000000000"):
            with self.assertRaises(ValueError):
                LocalMarkClient(project_id=identifier)

    def test_gate_unknown_or_stale_tls_fails_closed(self):
        client = LocalMarkClient()
        now = datetime.now(timezone.utc).isoformat()
        evidence = {"listing_status": "listed", "card_reachability": {"latest": {"success": True, "checked_at": now}},
                    "endpoint_tls": {"success": True}}
        with patch.object(client, "verify", return_value=evidence):
            self.assertFalse(client.gate("agent.example", tls=True)["passed"])
            evidence["endpoint_tls"]["checked_at"] = (datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()
            self.assertFalse(client.gate("agent.example", tls=True)["passed"])
            evidence["endpoint_tls"]["checked_at"] = now
            self.assertTrue(client.gate("agent.example", tls=True)["passed"])

    def test_action_stored_passes_requirements_and_rejects_unknown_mode(self):
        client = MagicMock()
        client.gate.return_value = {"passed": False}
        self.assertFalse(action.run({"LOCALMARK_TARGET": "agent.example"}, client)["passed"])
        client.gate.assert_called_once_with("agent.example", card_hours=24, a2a_hours=None, tls=True, signature=False)
        for env in ({"LOCALMARK_MODE": "execute"}, {"LOCALMARK_TLS": "yes"},
                    {"LOCALMARK_CARD_HOURS": "0"}, {"LOCALMARK_TARGET": ""}):
            with self.assertRaises(ValueError):
                action.run({"LOCALMARK_TARGET": "agent.example", **env}, client)

    def test_action_fresh_check_requires_structure_tls_and_recent_time(self):
        client = MagicMock()
        now = datetime.now(timezone.utc).isoformat()
        report = {"card_fetch": {"passed": True}, "structural_check": {"passed": True},
                  "endpoint_tls": {"passed": True}, "checked_at": now}
        client.check_card.return_value = report
        env = {"LOCALMARK_TARGET": "https://agent.example/.well-known/agent-card.json", "LOCALMARK_MODE": "check-card"}
        self.assertTrue(action.run(env, client)["passed"])
        report["structural_check"] = None
        self.assertFalse(action.run(env, client)["passed"])
        report["structural_check"] = {"passed": True}
        report["checked_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        self.assertFalse(action.run(env, client)["passed"])
        report["checked_at"] = now
        self.assertFalse(action.run({**env, "LOCALMARK_SIGNATURE": "true"}, client)["passed"])
        self.assertFalse(action.run({**env, "LOCALMARK_A2A_HOURS": "24"}, client)["passed"])


if __name__ == "__main__":
    unittest.main()
