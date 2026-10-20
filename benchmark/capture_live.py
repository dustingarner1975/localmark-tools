#!/usr/bin/env python3
"""Capture an explicitly incomplete, maintainer-judged live search sample.

The input contains private-to-this-exercise full public listing text and is not
copied into outputs. Only public listing names, IDs and source URLs are published.
Judgments below were authored by reading public skill declarations before running
either ranking for these queries. They are known positives, not exhaustive truth.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from run_benchmark import baseline_rank, load_engine, result_ids, sha256, evaluate_live_rankings

ROOT = Path(__file__).resolve().parent
CASES = [
    {"id": "live-pdf-create", "q": "generate PDF documents", "requirements": {},
     "judgments": {"relevant_ids": [195, 4632, 9022, 9142, 11261, 11463, 46188, 147699],
                   "unacceptable_ids": [3146], "rationale": "Known positive cards declare PDF creation or rendering. Paperknife declares extraction, not document creation."}},
    {"id": "live-pdf-fill", "q": "fill the fields in an existing PDF form", "requirements": {},
     "judgments": {"relevant_ids": [11260], "unacceptable_ids": [3146, 147699],
                   "rationale": "Emboss explicitly declares filling a PDF form from supplied data. Extraction and page rendering do not establish form filling."}},
    {"id": "live-pdf-extract", "q": "extract text from a PDF document", "requirements": {},
     "judgments": {"relevant_ids": [4, 3146, 11909, 11963, 46399], "unacceptable_ids": [11463],
                   "rationale": "Known positives declare PDF extraction or PDF-to-text/Markdown. Template-based PDF generation is a different operation."}},
    {"id": "live-weather", "q": "weather forecast for tomorrow", "requirements": {},
     "judgments": {"relevant_ids": [195, 490, 8868, 11805, 11834, 12011, 12150, 46252], "unacceptable_ids": [],
                   "rationale": "Known positives declare forecasts. Some have geographic or marine limits; no particular location is required by this query."}},
    {"id": "live-email-verify", "q": "validate an email address without sending email", "requirements": {},
     "judgments": {"relevant_ids": [195, 628, 9147, 11350, 12011], "unacceptable_ids": [491, 8793, 11495, 240762],
                   "rationale": "Known positives declare address validation. A mail-sending skill is not sufficient for this request, and the request excludes sending a message."}},
    {"id": "live-email-send", "q": "send an email message", "requirements": {},
     "judgments": {"relevant_ids": [491, 8793, 11495, 240762, 46188], "unacceptable_ids": [628, 11350],
                   "rationale": "Known positives declare sending mail; address-checking-only services are different."}},
    {"id": "live-geocode", "q": "convert a street address into latitude and longitude", "requirements": {},
     "judgments": {"relevant_ids": [9128, 9147, 11258, 11426, 11919], "unacceptable_ids": [],
                   "rationale": "Known positives explicitly advertise street/address geocoding, rather than only a city lookup or route calculation."}},
    {"id": "live-translation", "q": "translate text between languages", "requirements": {},
     "judgments": {"relevant_ids": [190, 195, 2091, 8820], "unacceptable_ids": [],
                   "rationale": "Known positives declare text translation. Language coverage differs and is not exhaustively evaluated by this broad request."}},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--engine", type=Path, default=ROOT.parent / "app" / "capability_search.py")
    parser.add_argument("--captured-at", required=True, help="Fixed UTC ISO capture time")
    args = parser.parse_args()
    rows = json.loads(args.candidates.read_text(encoding="utf-8"))
    now = datetime.fromisoformat(args.captured_at.replace("Z", "+00:00"))
    if now.tzinfo is None:
        raise ValueError("Capture time must have a timezone")
    engine = load_engine(args.engine)
    baseline, recommendations = {}, {}
    for case in CASES:
        case["judgments"]["constraint_ineligible_ids"] = []
        case["judgments"]["no_match_expected"] = False
        case["judgments"]["complete"] = False
        baseline[case["id"]] = baseline_rank(rows, case["q"], case["requirements"], now)
        recommendations[case["id"]] = result_ids(engine.rank_agents(rows, case["q"], case["requirements"], now=now))
    published_ids = {i for case in CASES for field in ("relevant_ids", "unacceptable_ids") for i in case["judgments"][field]}
    published_ids.update(i for result in baseline.values() for i in result[:5])
    published_ids.update(i for result in recommendations.values() for i in result[:5])
    provenance = [{"id": row["id"], "name": row["name"], "card_url": row["card_url"],
                   "profile_url": "https://localmark.ai/agents/%s" % row["id"]} for row in rows if row["id"] in published_ids]
    missing = published_ids - {row["id"] for row in rows}
    if missing:
        raise ValueError("Judgment references missing public listing IDs: %s" % sorted(missing))
    capture = {"schema_version": "1", "metadata": {
        "captured_at": now.astimezone(timezone.utc).isoformat(), "candidate_count": len(rows),
        "candidate_snapshot_sha256": sha256(args.candidates), "ranking_module_sha256": sha256(args.engine),
        "selection_method": "Eight manually chosen natural-language task requests and known positive skill declarations, authored before examining these rankings. This subset focuses on longer requests, not representative keyword-search traffic. Not a random or exhaustive sample.",
        "judgments_complete": False,
        "scope": "One-time observed search sample using public stored declarations. Not a task test, independent assessment, competitor comparison, or exhaustive relevance assessment.",
        "replay_limit": "Ranked ID captures and scoring can be replayed offline. Full candidate text is not redistributed; exact live reranking requires the original snapshot. Current listings can change.",
        "rights": "Publisher names and card URLs are public source references; no license to third-party content is granted. Full descriptions and Agent Cards are omitted."},
        "cases": CASES, "baseline_results": baseline, "recommendation_results": recommendations,
        "public_listing_references": provenance}
    (ROOT / "live-capture.json").write_text(json.dumps(capture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cases_only = {"schema_version": "1", "metadata": capture["metadata"], "cases": CASES,
                  "public_listing_references": provenance}
    (ROOT / "live-cases.json").write_text(json.dumps(cases_only, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"schema_version": "1", "synthetic": False, "metadata": capture["metadata"],
              "public_listing_references": provenance,
              **evaluate_live_rankings(CASES, baseline, recommendations)}
    (ROOT / "live-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summaries"], indent=2))


if __name__ == "__main__":
    main()
