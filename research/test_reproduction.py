import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

from research_reports import generate_reports


class ReportReproductionTests(unittest.TestCase):
    def _snapshot(self, folder, bad_hash=False):
        rows = [{"publisher_domain":"publisher.example","observations":{"signature_status":"verified",
                 "read_only_a2a_probe":{"state":"a2a_response"},"endpoint_tls":{"passed":True}},
                 "publisher_declared":{"skills":[{"tags":["PDF"]}]}},
                {"publisher_domain":"publisher.example","observations":{},"publisher_declared":{"skills":[{"tags":["PDF"]}]}}]
        data = gzip.compress(("\n".join(json.dumps(row) for row in rows)+"\n").encode(),mtime=0)
        (folder/"2026-10-19.jsonl.gz").write_bytes(data)
        (folder/"2026-10-19.json").write_text(json.dumps({"gzip_sha256":"bad" if bad_hash else hashlib.sha256(data).hexdigest(),"record_count":2}),encoding="utf-8")

    def test_counts_are_reproduced_and_tags_count_distinct_publishers(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            self._snapshot(folder)
            result=generate_reports(folder,datetime(2026,10,20,tzinfo=timezone.utc))
            report=json.loads((folder/"reports/2026-10.json").read_text(encoding="utf-8"))
            self.assertEqual(result["updated"],["2026-10"])
            self.assertFalse(report["calendar_month_closed"])
            self.assertEqual(report["latest"]["public_agents"],2)
            self.assertEqual(report["latest"]["distinct_publishers"],1)
            self.assertEqual(report["latest"]["verified_signature_percent"],50)
            self.assertEqual(report["latest"]["common_declared_tags"],[{"tag":"pdf","distinct_publishers":1}])

    def test_checksum_failure_never_publishes_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            self._snapshot(folder,bad_hash=True)
            with self.assertRaises(ValueError):
                generate_reports(folder,datetime(2026,10,20,tzinfo=timezone.utc))
            self.assertFalse((folder/"reports/2026-10.json").exists())


if __name__ == "__main__":
    unittest.main()
