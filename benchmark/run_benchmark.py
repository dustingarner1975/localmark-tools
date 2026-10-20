#!/usr/bin/env python3
"""Run the public synthetic benchmark or score externally captured rankings.

Python 3.10+, standard library only. No network access or database is used.
"""
import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
K = 5


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    """Use explicit LF so report bytes are reproducible on Windows and Linux."""
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def as_time(value):
    if not value:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def oracle_allows(agent, requirements, now):
    """Independent supported-constraint predicate for the historical baseline.

    This checks fixture observations, never capabilities or real endpoint behaviour.
    Natural language interpretation is deliberately absent from the old baseline.
    """
    card = agent.get("card") or {}
    declared_auth = bool(card.get("securityRequirements") or card.get("security") or card.get("authentication"))
    auth = requirements.get("auth")
    if auth == "none" and declared_auth or auth == "declared" and not declared_auth:
        return False
    if requirements.get("signature") and agent.get("signature_status") != requirements["signature"]:
        return False
    bindings = [i.get("protocolBinding") for i in (card.get("supportedInterfaces") or []) if isinstance(i, dict)]
    bindings.append(card.get("preferredTransport"))
    if requirements.get("protocol") and requirements["protocol"] not in bindings:
        return False
    if requirements.get("tls_reachable"):
        tls = agent.get("endpoint_tls") or {}
        if not (tls.get("reachable") if "reachable" in tls else tls.get("success")):
            return False
    for key, observation, confirmed in (
        ("checked_within_hours", {"checked_at": agent.get("last_verified")}, True),
        ("a2a_response_within_hours", agent.get("read_only_a2a_probe") or {}, None),
    ):
        if requirements.get(key):
            checked = as_time(observation.get("checked_at"))
            if not checked or checked > now or (now - checked).total_seconds() > float(requirements[key]) * 3600:
                return False
            if confirmed is None and observation.get("state") != "a2a_response":
                return False
    return True


def baseline_rank(agents, query, requirements, now):
    """Reproduce the previous SQL whole-phrase ILIKE eligibility and CASE rank.

    Relevant parts: names 100/80/60, skill name 55/50, tags 40,
    skill description 25, agent description 10. All natural language query
    words must occur as one consecutive substring. Explicit supported filters
    receive the same observations. Publisher rotation and signature/newness
    tie breaks mirror the old directory search.
    """
    query = query.casefold().strip()
    candidates = []
    for agent in agents:
        if not oracle_allows(agent, requirements, now):
            continue
        name = agent.get("name", "").casefold()
        description = agent.get("description", "").casefold()
        capabilities = agent.get("capabilities") or []
        names = [c.get("name", "").casefold() for c in capabilities]
        tags = [" ".join(c.get("tags") or []).casefold() for c in capabilities]
        descriptions = [c.get("description", "").casefold() for c in capabilities]
        all_fields = [name, description] + names + tags + descriptions
        if query and not any(query in field for field in all_fields):
            continue
        score = (100 if name == query else 80 if name.startswith(query) else 60 if query in name
                 else 55 if query in names else 50 if any(query in n for n in names)
                 else 40 if any(query in t for t in tags) else 25 if any(query in d for d in descriptions)
                 else 10) if query else 0
        candidates.append((agent, score))
    candidates.sort(key=lambda x: (-x[1], -(x[0].get("signature_status") == "verified"),
                                   -as_time(x[0]["first_seen"]).timestamp(), -x[0]["id"]))
    rotations = {}
    ranked = []
    for agent, score in candidates:
        group = (agent.get("publisher_domain"), score)
        rotations[group] = rotations.get(group, 0) + 1
        ranked.append((agent, score, rotations[group]))
    ranked.sort(key=lambda x: (-x[1], x[2], -(x[0].get("signature_status") == "verified"),
                              -as_time(x[0]["first_seen"]).timestamp(), -x[0]["id"]))
    return [agent["id"] for agent, _, _ in ranked]


def result_ids(value):
    if isinstance(value, dict):
        value = value.get("items", value.get("ranked_ids", []))
    result = []
    for item in value or []:
        identifier = item.get("id", item.get("agent_id")) if isinstance(item, dict) else item
        if identifier not in result:
            result.append(identifier)
    return result


def score_case(case, ranked):
    judgments = case["judgments"]
    relevant = set(judgments.get("relevant_ids", []))
    top = result_ids(ranked)[:K]
    hits = [identifier for identifier in top if identifier in relevant]
    rejected = set(judgments.get("unacceptable_ids", []))
    constrained = set(judgments.get("constraint_ineligible_ids", []))
    first = next((rank for rank, identifier in enumerate(top, 1) if identifier in relevant), None)
    no_match = bool(judgments.get("no_match_expected", not relevant))
    return {
        "ranked_ids": result_ids(ranked), "top_5_ids": top,
        "relevant_returned_ids": hits,
        "precision_at_5": round(len(hits) / K, 6) if not no_match else None,
        "precision_retrieved_at_5": round(len(hits) / len(top), 6) if top and not no_match else (0.0 if not no_match else None),
        "recall_at_5": round(len(hits) / len(relevant), 6) if relevant else None,
        "reciprocal_rank_at_5": round(1 / first, 6) if first else (0.0 if not no_match else None),
        "result_fill_rate_at_5": round(len(top) / K, 6),
        "no_match_correct": not top if no_match else None,
        "targeted_distractor_ids": [identifier for identifier in top if identifier in rejected],
        "constraint_violation_ids": [identifier for identifier in top if identifier in constrained],
        "unjudged_returned_ids": [identifier for identifier in top if identifier not in relevant and identifier not in rejected],
    }


def summary(scores):
    positive = [s for s in scores if s["recall_at_5"] is not None]
    negative = [s for s in scores if s["no_match_correct"] is not None]
    def average(key, rows):
        return round(sum(s[key] for s in rows) / len(rows), 6) if rows else None
    return {
        "query_count": len(scores), "positive_query_count": len(positive), "no_match_query_count": len(negative),
        "macro_precision_at_5": average("precision_at_5", positive),
        "macro_precision_retrieved_at_5": average("precision_retrieved_at_5", positive),
        "macro_recall_at_5": average("recall_at_5", positive),
        "mean_reciprocal_rank_at_5": average("reciprocal_rank_at_5", positive),
        "mean_result_fill_rate_at_5": average("result_fill_rate_at_5", positive),
        "no_match_correct_count": sum(s["no_match_correct"] for s in negative),
        "no_match_accuracy": round(sum(s["no_match_correct"] for s in negative) / len(negative), 6) if negative else None,
        "top_5_constraint_violations": sum(len(s["constraint_violation_ids"]) for s in scores),
        "top_5_targeted_distractors": sum(len(s["targeted_distractor_ids"]) for s in scores),
    }


def evaluate_rankings(cases, baseline_results, recommendation_results):
    """Score query-id -> ordered ID arrays or {items:[{id:...}]} captures.

    For a live replay, every case must provide manual judgments over its frozen
    candidate snapshot. Missing query captures raise, rather than scoring as []
    and making no-match cases look successful. This function makes no network calls.
    """
    rows = []
    seen = set()
    for case in cases:
        identifier = case["id"]
        if identifier in seen:
            raise ValueError("Duplicate benchmark query ID: " + identifier)
        seen.add(identifier)
        for captures in (baseline_results, recommendation_results):
            if identifier not in captures:
                raise ValueError("Missing result capture for query: " + identifier)
        rows.append({**case, "baseline": score_case(case, baseline_results[identifier]),
                     "recommendation": score_case(case, recommendation_results[identifier])})
    return {"k": K, "summaries": {name: summary([row[name] for row in rows]) for name in ("baseline", "recommendation")},
            "queries": rows}


def evaluate_live_rankings(cases, baseline_results, recommendation_results):
    """Score known positives without treating unjudged live results as wrong.

    No precision or recall is reported because the relevance set is incomplete.
    A miss means no *known positive* appeared, not that all returned results fail.
    """
    full = evaluate_rankings(cases, baseline_results, recommendation_results)
    summaries = {}
    for engine in ("baseline", "recommendation"):
        scored = [row[engine] for row in full["queries"]]
        summaries[engine] = {
            "query_count": len(scored),
            "known_positive_hit_at_5": round(sum(bool(s["relevant_returned_ids"]) for s in scored) / len(scored), 6) if scored else None,
            "known_positive_mrr_at_5": round(sum(s["reciprocal_rank_at_5"] or 0 for s in scored) / len(scored), 6) if scored else None,
            "top_5_judged_distractors": sum(len(s["targeted_distractor_ids"]) for s in scored),
        }
        for row in full["queries"]:
            result = row[engine]
            row[engine] = {"ranked_ids": result["ranked_ids"], "top_5_ids": result["top_5_ids"],
                           "known_positive_returned_ids": result["relevant_returned_ids"],
                           "known_positive_hit_at_5": bool(result["relevant_returned_ids"]),
                           "known_positive_reciprocal_rank_at_5": result["reciprocal_rank_at_5"],
                           "judged_distractor_ids": result["targeted_distractor_ids"],
                           "unjudged_returned_ids": result["unjudged_returned_ids"]}
    return {"k": K, "judgments_complete": False, "summaries": summaries,
            "metrics_scope": "Only known-positive hit rate and reciprocal rank; no precision or recall because live judgments are incomplete. An unjudged result is not classified as irrelevant.",
            "queries": full["queries"]}


def load_engine(path):
    spec = importlib.util.spec_from_file_location("benchmark_capability_search", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_fixture(fixtures_path, engine_path):
    fixture = read_json(fixtures_path)
    engine = load_engine(engine_path)
    now = as_time(fixture["fixed_now"])
    baseline, recommendation = {}, {}
    interpretations = {}
    for case in fixture["queries"]:
        identifier, query, requirements = case["id"], case["q"], case.get("requirements", {})
        baseline[identifier] = baseline_rank(fixture["agents"], query, requirements, now)
        result = engine.rank_agents(fixture["agents"], query, requirements, now=now)
        recommendation[identifier] = result_ids(result)
        interpretations[identifier] = {"interpreted_query": result.get("interpreted_query"),
                                       "applied_requirements": result.get("requirements", {})}
    evaluated = evaluate_rankings(fixture["queries"], baseline, recommendation)
    for case in evaluated["queries"]:
        case.update(interpretations[case["id"]])
    return {
        "schema_version": "1", "benchmark_version": fixture["benchmark_version"], "fixed_now": fixture["fixed_now"],
        "title": fixture["title"], "synthetic": True, "scope": fixture["scope"],
        "license": "MIT", "corpus_size": len(fixture["agents"]),
        "snapshot_hashes": {"fixtures_sha256": sha256(fixtures_path), "ranking_module_sha256": sha256(engine_path)},
        "metrics": {
            "precision_at_5": "Relevant retrieved in the first five divided by 5, even if fewer results were returned.",
            "precision_retrieved_at_5": "Relevant retrieved divided by the number actually returned up to five; zero for an empty positive query.",
            "recall_at_5": "Relevant retrieved in the first five divided by all manually judged relevant fixture agents.",
            "reciprocal_rank_at_5": "1 / first relevant result position within five, or zero if none.",
            "no_match_accuracy": "Fraction of designated no-match queries returning no candidates; excluded from relevance averages.",
            "constraint_violations": "Count of returned top-five IDs manually annotated as failing a required evidence/authentication/transport constraint.",
            "caveat": "A small maintainer-authored fixture regression exercise; results do not establish live task quality, independent assessment, or superiority to other directories."
        },
        **evaluated,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "fixtures.json")
    parser.add_argument("--engine", type=Path, default=(ROOT / "capability_search.py") if (ROOT / "capability_search.py").exists() else ROOT.parent / "app" / "capability_search.py")
    parser.add_argument("--output", type=Path, default=ROOT / "report.json")
    parser.add_argument("--captures", type=Path, help="Score a frozen live replay JSON with cases, baseline_results, recommendation_results, and metadata")
    args = parser.parse_args()
    if args.captures:
        capture = read_json(args.captures)
        evaluator = evaluate_live_rankings if capture.get("metadata", {}).get("judgments_complete") is False else evaluate_rankings
        report = {"schema_version": "1", "synthetic": False, "scope": "One-time maintainer-judged observed search sample, not a task test.",
                  "metadata": capture.get("metadata", {}),
                  **evaluator(capture["cases"], capture["baseline_results"], capture["recommendation_results"])}
    else:
        report = run_fixture(args.fixtures, args.engine)
    write_json(args.output, report)
    print(json.dumps(report["summaries"], indent=2))


if __name__ == "__main__":
    main()
