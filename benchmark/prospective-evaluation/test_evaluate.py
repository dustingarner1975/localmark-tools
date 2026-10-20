import copy
import unittest

from evaluate import evaluate, build_pool, validate_rankings


class ProspectiveScoringTests(unittest.TestCase):
    def setUp(self):
        # Isolated scoring fixtures; never run the frozen prospective queries.
        self.queries = {"version":"unit-test-only", "queries":[{"id":"q1", "query":"fixture", "requirements":{}},
                                                                 {"id":"q2", "query":"fixture-empty", "requirements":{}}]}
        self.captures = [{"system_id":"candidate-a", "query_set_version":"unit-test-only", "captured_at":"2026-10-20T00:00:00Z",
                         "queries":[{"query_id":"q1", "status":"ok", "agent_ids":["1","2"],
                                     "candidates":[{"agent_id":"1", "name":"one", "rank":1, "score":99, "system_id":"candidate-a"}]},
                                    {"query_id":"q2", "status":"empty", "agent_ids":[]}]}]
        self.judges = [{"judge_id":judge,"query_set_version":"unit-test-only","independent_of_ranker_development":True,
                        "blind_to_system_rankings":True,"conflict_disclosure":"None",
                        "queries":[{"query_id":"q1","complete_pool":True,"judgments":[{"agent_id":"1","grade":2,"reason":"fixture match"},
                                                                                             {"agent_id":"2","grade":0,"reason":"fixture unrelated"}]},
                                   {"query_id":"q2","complete_pool":True,"judgments":[]}]} for judge in ("judge-one","judge-two")]

    def test_no_judges_no_scores(self):
        report = evaluate(self.captures,[],self.queries)
        self.assertEqual(report["status"],"awaiting_external_judgments")
        self.assertIsNone(report["systems"][0]["mean_pooled_ndcg_at_5"])
        self.assertEqual(report["systems"][0]["scored_queries"],0)

    def test_one_judge_is_insufficient_and_unblinded_judge_is_excluded(self):
        self.judges[1]["blind_to_system_rankings"] = False
        report = evaluate(self.captures,self.judges,self.queries)
        self.assertEqual(report["judged_query_count"],0)
        self.assertEqual(len(report["excluded_judges"]),1)

    def test_two_judges_allow_scoring_with_fixed_denominator(self):
        report = evaluate(self.captures,self.judges,self.queries)
        self.assertEqual(report["status"],"externally_judged_self_reported")
        self.assertEqual(report["systems"][0]["mean_precision_at_5"],0.2)
        self.assertEqual(report["systems"][0]["mean_pooled_ndcg_at_5"],1.0)
        self.assertEqual(report["systems"][0]["mean_reciprocal_rank_at_5"],1.0)

    def test_missing_candidate_grade_cannot_count_as_irrelevant(self):
        self.judges[1]["queries"][0]["judgments"].pop()
        report = evaluate(self.captures,self.judges,self.queries)
        self.assertEqual(report["status"],"partially_judged")
        self.assertFalse(report["coverage"][0]["judged"])
        self.assertIsNone(report["systems"][0]["mean_precision_at_5"])

    def test_disagreement_remains_visible(self):
        self.judges[1]["queries"][0]["judgments"][1]["grade"] = 2
        report = evaluate(self.captures,self.judges,self.queries)
        self.assertEqual(len(report["disagreements"]),1)
        self.assertEqual(report["disagreements"][0]["agent_id"],"2")

    def test_failed_or_missing_capture_is_not_a_no_match(self):
        self.captures[0]["queries"][1]["status"] = "error"
        report = evaluate(self.captures,self.judges,self.queries)
        self.assertEqual(report["systems"][0]["missing_or_failed_queries"],["q2"])
        self.assertEqual(report["systems"][0]["scored_queries"],1)

    def test_pool_hides_system_rank_score_and_order(self):
        pool = build_pool(self.captures,self.queries)
        self.assertEqual(pool["queries"][0]["candidates"][0],{"agent_id":"1","name":"one"})
        self.assertNotIn("candidate-a",str(pool))
        self.assertNotIn("score",str(pool))

    def test_duplicate_rankings_and_judges_rejected(self):
        self.captures[0]["queries"][0]["agent_ids"] = ["1","1"]
        with self.assertRaises(ValueError):
            evaluate(self.captures,self.judges,self.queries)
        self.captures[0]["queries"][0]["agent_ids"] = ["1","2"]
        self.judges[1]["judge_id"] = "JUDGE-ONE"
        with self.assertRaises(ValueError):
            evaluate(self.captures,self.judges,self.queries)


if __name__ == "__main__":
    unittest.main()
