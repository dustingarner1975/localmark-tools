#!/usr/bin/env python3
"""Pool blinded candidates and score only sufficiently judged prospective captures."""

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent
K = 5


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+"\n",
                          encoding="utf-8", newline="\n")


def verify_queries(path, manifest_path):
    manifest = read(manifest_path)
    expected = manifest["files"]["queries.json"]
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
        raise ValueError("Frozen query checksum mismatch")
    return read(path)


def validate_rankings(captures, queries):
    query_ids = {q["id"] for q in queries["queries"]}
    seen = set()
    for capture in captures:
        system = capture.get("system_id")
        if not isinstance(system, str) or not system.strip() or len(system) > 80 or system in seen:
            raise ValueError("Each capture needs a distinct system_id of 1..80 characters")
        seen.add(system)
        if capture.get("query_set_version") != queries["version"]:
            raise ValueError("Capture query_set_version differs from frozen queries")
        if not isinstance(capture.get("queries"), list):
            raise ValueError("Capture queries must be an array")
        contained = set()
        for result in capture["queries"]:
            qid = result.get("query_id")
            if qid not in query_ids or qid in contained:
                raise ValueError("Unknown or duplicate captured query_id")
            contained.add(qid)
            ids = result.get("agent_ids")
            if not isinstance(ids, list) or len(ids) > 20 or any(not isinstance(v, str) or not v for v in ids) or len(set(ids)) != len(ids):
                raise ValueError("Ranked agent_ids must be up to 20 unique non-empty strings")
            if result.get("status") not in ("ok", "empty", "needs_clarification", "error"):
                raise ValueError("Captured status must explicitly distinguish errors from empty results")
            if result["status"] == "error" and ids:
                raise ValueError("An error cannot contain scored results")
    return captures


def build_pool(captures, queries):
    pooled = {q["id"]: {} for q in queries["queries"]}
    for capture in captures:
        for result in capture["queries"]:
            if result["status"] == "error":
                continue
            candidates = {str(v["agent_id"]): v for v in result.get("candidates", [])}
            for aid in result["agent_ids"][:K]:
                original = candidates.get(aid, {"agent_id": aid})
                candidate = {key:original[key] for key in (
                    "agent_id", "name", "profile_url", "card_url", "publisher_declared_excerpt",
                    "declared_skills", "evidence", "publisher_content_license") if key in original}
                # Never disclose ranking position or retrieving system to judges.
                candidate.pop("rank", None)
                candidate.pop("system_id", None)
                candidate.pop("score", None)
                pooled[result["query_id"]].setdefault(aid, candidate)
    return {"query_set_version": queries["version"], "scope": "Unordered pooled top-5 candidates. System labels and rank positions intentionally omitted.",
            "queries": [{"query_id": q["id"], "query": q["query"], "requirements": q["requirements"],
                         "candidates": [pooled[q["id"]][aid] for aid in sorted(pooled[q["id"]])]} for q in queries["queries"]]}


def validate_judges(judgments, queries):
    query_ids = {q["id"] for q in queries["queries"]}
    seen = set()
    accepted = []
    excluded = []
    for document in judgments:
        judge = document.get("judge_id")
        if not isinstance(judge, str) or not judge.strip() or len(judge) > 80 or judge.casefold() in seen:
            raise ValueError("Each judge needs a distinct pseudonymous judge_id of 1..80 characters")
        seen.add(judge.casefold())
        if document.get("query_set_version") != queries["version"]:
            raise ValueError("Judge query_set_version differs from frozen queries")
        if document.get("independent_of_ranker_development") is not True or document.get("blind_to_system_rankings") is not True:
            excluded.append({"judge_id": judge, "reason": "Independent/blind self-attestations are absent or false"})
            continue
        if not isinstance(document.get("conflict_disclosure"), str) or not document["conflict_disclosure"].strip():
            raise ValueError("Each external judge must include a conflict_disclosure")
        by_query = {}
        for item in document.get("queries", []):
            qid = item.get("query_id")
            if qid not in query_ids or qid in by_query:
                raise ValueError("Unknown or duplicate judged query_id")
            grades = {}
            for entry in item.get("judgments", []):
                aid, grade = entry.get("agent_id"), entry.get("grade")
                if not isinstance(aid, str) or not aid or aid in grades or isinstance(grade, bool) or not isinstance(grade,int) or grade not in (0, 1, 2):
                    raise ValueError("Judgments need unique agent_ids and integer grades 0, 1 or 2")
                if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
                    raise ValueError("Every grade needs a reason")
                grades[aid] = grade
            by_query[qid] = {"complete_pool": item.get("complete_pool") is True, "grades": grades}
        accepted.append({"judge_id": judge, "conflict_disclosure": document["conflict_disclosure"], "queries": by_query})
    return accepted, excluded


def _dcg(grades):
    return sum((2**grade-1)/math.log2(i+2) for i,grade in enumerate(grades[:K]))


def evaluate(captures, judgments, queries, minimum_judges=2):
    if isinstance(minimum_judges, bool) or minimum_judges < 2:
        raise ValueError("At least two external judges are required")
    captures = validate_rankings(captures, queries)
    judges, excluded = validate_judges(judgments, queries)
    pool = build_pool(captures, queries)
    pooled = {q["query_id"]: {str(c["agent_id"]) for c in q["candidates"]} for q in pool["queries"]}
    grades = {}
    coverage = []
    disagreements = []
    for query in queries["queries"]:
        qid = query["id"]
        complete = [judge for judge in judges if judge["queries"].get(qid, {}).get("complete_pool")
                    and pooled[qid] <= set(judge["queries"][qid]["grades"])]
        coverage.append({"query_id": qid, "pooled_candidate_count": len(pooled[qid]), "complete_external_judges": len(complete),
                         "judged": len(complete) >= minimum_judges})
        if len(complete) < minimum_judges:
            continue
        grades[qid] = {aid: mean(judge["queries"][qid]["grades"][aid] for judge in complete) for aid in pooled[qid]}
        for aid in sorted(pooled[qid]):
            values = [judge["queries"][qid]["grades"][aid] for judge in complete]
            if len(set(values)) > 1:
                disagreements.append({"query_id": qid, "agent_id": aid, "grades": values})
    systems = []
    for capture in captures:
        scored = []
        missing_or_failed = []
        by_query = {q["query_id"]: q for q in capture["queries"]}
        for q in queries["queries"]:
            result = by_query.get(q["id"])
            if result is None or result["status"] == "error":
                missing_or_failed.append(q["id"])
                continue
            if q["id"] not in grades:
                continue
            judged = grades[q["id"]]
            ranked = [judged[aid] for aid in result["agent_ids"][:K]]
            ideal = sorted(judged.values(), reverse=True)
            idcg = _dcg(ideal)
            relevant = [i+1 for i,v in enumerate(ranked) if v >= 1]
            scored.append({"query_id": q["id"], "pooled_ndcg_at_5": round(_dcg(ranked)/idcg, 6) if idcg else None,
                           "precision_at_5": round(sum(v >= 1 for v in ranked)/K, 6),
                           "reciprocal_rank_at_5": round(1/relevant[0], 6) if relevant else 0,
                           "returned_at_5": len(ranked), "judged_pool_has_relevant": any(v >= 1 for v in ideal)})
        positive = [row for row in scored if row["judged_pool_has_relevant"]]
        ndcg = [row["pooled_ndcg_at_5"] for row in scored if row["pooled_ndcg_at_5"] is not None]
        systems.append({"system_id": capture["system_id"], "captured_at": capture.get("captured_at"),
                        "missing_or_failed_queries": missing_or_failed, "scored_queries": len(scored),
                        "mean_pooled_ndcg_at_5": round(mean(ndcg), 6) if ndcg else None,
                        "mean_precision_at_5": round(mean(row["precision_at_5"] for row in positive), 6) if positive else None,
                        "mean_reciprocal_rank_at_5": round(mean(row["reciprocal_rank_at_5"] for row in positive), 6) if positive else None,
                        "queries": scored})
    complete_count = sum(c["judged"] for c in coverage)
    return {"query_set_version": queries["version"],
            "status": "awaiting_external_judgments" if not complete_count else "partially_judged" if complete_count < len(coverage) else "externally_judged_self_reported",
            "minimum_external_judges": minimum_judges, "judged_query_count": complete_count, "query_count": len(coverage),
            "coverage": coverage, "systems": systems,
            "judge_disclosures": [{"judge_id": j["judge_id"], "conflict_disclosure": j["conflict_disclosure"]} for j in judges],
            "excluded_judges": excluded, "disagreements": disagreements,
            "limitations": ["Independence and blinding are self-attested, not verified identities.",
                "Only judged pooled top-5 candidates are scored; no Internet-wide recall is estimated.",
                "Precision uses a denominator of 5; relevance means average external grade >= 1.",
                "Only queries with pooled relevant candidates contribute to aggregate precision and reciprocal rank.",
                "Missing/error captures are reported, never interpreted as successful no-match results.",
                "A partial report is not a complete comparison; query, corpus, time and requirements must be comparable.",
                "This evaluates retrieval from declarations/evidence, not task execution or safety."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", default=str(ROOT/"queries.json"))
    parser.add_argument("--manifest", default=str(ROOT/"manifest.json"))
    parser.add_argument("--rankings", action="append", required=True)
    parser.add_argument("--judgments", action="append", default=[])
    parser.add_argument("--output", default="evaluation.json")
    parser.add_argument("--pool-output", help="Write unordered candidates with system names/ranks removed for judges")
    args = parser.parse_args()
    queries = verify_queries(args.queries, args.manifest)
    captures = [read(path) for path in args.rankings]
    report = evaluate(captures, [read(path) for path in args.judgments], queries)
    write(args.output, report)
    if args.pool_output:
        write(args.pool_output, build_pool(captures, queries))
    print(report["status"], f"({report['judged_query_count']}/{report['query_count']} queries judged)")


if __name__ == "__main__":
    main()
