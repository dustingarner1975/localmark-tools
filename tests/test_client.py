import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from localmark_client import LocalMarkClient


class ClientTests(unittest.TestCase):
    def test_gate_requires_fresh_evidence(self):
        now = datetime.now(timezone.utc).isoformat()
        evidence = {"listing_status": "listed",
                    "card_reachability": {"latest": {"success": True, "checked_at": now}},
                    "read_only_a2a_probe": {"state": "a2a_response", "checked_at": now},
                    "endpoint_tls": {"success": True}}
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


if __name__ == "__main__":
    unittest.main()
