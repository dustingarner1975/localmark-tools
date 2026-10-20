"""Tests for benchmark scoring mistakes, independent from search ranking."""
import unittest
import tempfile
from pathlib import Path

from run_benchmark import evaluate_live_rankings, evaluate_rankings, score_case, write_json


class BenchmarkScoringTests(unittest.TestCase):
    def setUp(self):
        self.positive = {"id": "a", "q": "example", "judgments": {
            "relevant_ids": [1, 2], "unacceptable_ids": [3],
            "constraint_ineligible_ids": [3], "no_match_expected": False}}
        self.negative = {"id": "b", "q": "no fixture", "judgments": {
            "relevant_ids": [], "no_match_expected": True}}

    def test_short_list_does_not_claim_perfect_precision_at_five(self):
        scored = score_case(self.positive, [1])
        self.assertEqual(scored["precision_at_5"], 0.2)
        self.assertEqual(scored["precision_retrieved_at_5"], 1.0)
        self.assertEqual(scored["recall_at_5"], 0.5)
        self.assertEqual(scored["result_fill_rate_at_5"], 0.2)

    def test_duplicates_do_not_inflate_recall(self):
        scored = score_case(self.positive, [1, 1, 1, 1, 1])
        self.assertEqual(scored["relevant_returned_ids"], [1])
        self.assertEqual(scored["recall_at_5"], 0.5)

    def test_wrong_recommendation_counts_as_constraint_violation(self):
        scored = score_case(self.positive, [3, 4, 1, 2])
        self.assertEqual(scored["constraint_violation_ids"], [3])
        self.assertEqual(scored["unjudged_returned_ids"], [4])
        self.assertEqual(scored["reciprocal_rank_at_5"], 0.333333)

    def test_no_match_queries_are_separate_from_positive_averages(self):
        scored = evaluate_rankings([self.positive, self.negative], {"a": [], "b": []}, {"a": [1, 2], "b": [3]})
        self.assertEqual(scored["summaries"]["baseline"]["no_match_accuracy"], 1.0)
        self.assertEqual(scored["summaries"]["recommendation"]["no_match_accuracy"], 0.0)
        self.assertEqual(scored["summaries"]["recommendation"]["macro_recall_at_5"], 1.0)

    def test_missing_capture_is_not_treated_as_successful_no_match(self):
        with self.assertRaisesRegex(ValueError, "Missing result capture"):
            evaluate_rankings([self.negative], {}, {})

    def test_duplicate_query_ids_fail(self):
        with self.assertRaisesRegex(ValueError, "Duplicate benchmark"):
            evaluate_rankings([self.positive, self.positive], {"a": []}, {"a": []})

    def test_live_incomplete_judgments_do_not_report_precision_or_recall(self):
        scored = evaluate_live_rankings([self.positive], {"a": [3]}, {"a": [9, 1]})
        summary = scored["summaries"]["recommendation"]
        self.assertEqual(summary["known_positive_hit_at_5"], 1.0)
        self.assertEqual(summary["known_positive_mrr_at_5"], 0.5)
        self.assertNotIn("macro_precision_at_5", summary)
        self.assertNotIn("recall_at_5", scored["queries"][0]["recommendation"])
        self.assertEqual(scored["queries"][0]["recommendation"]["unjudged_returned_ids"], [9])

    def test_report_serialization_uses_lf_on_every_platform(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "report.json"
            write_json(target, {"example": [1, 2]})
            self.assertTrue(target.read_bytes().endswith(b"\n"))
            self.assertNotIn(b"\r\n", target.read_bytes())


if __name__ == "__main__":
    unittest.main()
