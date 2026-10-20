# LocalMark public capability search benchmark

This is a small, public regression exercise for LocalMark's capability search.
Its 34 cards, 24 queries and relevance judgments were written by LocalMark's
maintainer. All agent names and `.example` addresses are fictional. Nothing is
sent to an agent and no task is executed. The results measure search against
these judgments, rather than whether any real agent can perform a task.

This is not an independent assessment or a comparison with another directory.
The ranking code and fixtures are developed by the same project. An improvement
on these fixtures needs to be checked on additional searches and actual users.
We publish failures and the complete inputs so others can challenge the results.
This development set was used to identify and fix ranking issues during the
release, including operation matching and natural-language signature constraints.
It is not a held-out test set; high scores should be read with that limitation.

## Reproduce the fixture report

Download `fixtures.json`, `run_benchmark.py` and `capability_search.py` into one
folder. Python 3.10 or later is enough; no packages, key, account, network or
database is required.

```console
python run_benchmark.py --engine capability_search.py --output my-report.json
```

Within the application source checkout, run:

```console
python benchmark/run_benchmark.py
python -m unittest discover -s benchmark -p test_benchmark.py
```

The report includes SHA-256 digests of the exact fixture file and ranking module.
Report JSON uses UTF-8 and LF line endings on every platform. Input checksums
refer to the raw distributed bytes; the repository preserves benchmark artifact
bytes on checkout rather than silently converting their line endings.
The fixture clock is fixed at `2026-10-20T12:00:00+00:00`; relative freshness
requirements are evaluated at that time, even when the exercise is replayed later.
Generation time, wall-clock speed and external network behaviour cannot affect
the reported rankings. `build_fixtures.py` reproduces the fixture JSON from the
manually authored records if you download that file too.

## What is being compared

The baseline implements LocalMark's previous whole-phrase keyword search: the
entire query must appear as one consecutive phrase in a name, description, skill
name, skill description or tag string. Its name/skill/tag/description priority,
publisher rotation and signature/newness tie breaks follow the previous SQL.
Explicit evidence filters are still applied. The baseline does not interpret
natural-language requests such as “without an API key”.

The recommendation search uses the same shared ranker as the website, MCP and
client API. It interprets task terms and supported constraints, matches declared
skills, and ranks candidates using those declarations and stored observations.
Neither implementation fetches a card during the benchmark.

Examples deliberately distinguish PDF generation from form filling and text
extraction, email verification from email sending, company records from stock
quotes, and performing a payment check from explaining payment documentation.
There are recent/stale card and protocol observations, successful/failed TLS,
unsigned/signed cards, declared authentication and a missing-capability case.
The PDF viewer and payment documentation examples deliberately test whether
incidental or negated words can lead to a misleading recommendation.

## Judgments and metrics

Every query includes a human-authored rationale and relevant IDs. Where useful,
it also lists targeted distractors and IDs explicitly ineligible under a required
constraint. These are visible in both the fixture and the report.

- **Precision@5:** relevant results among the first five, divided by five. A
  two-result shortlist with two relevant results scores 0.4, not 1.0.
- **Precision of returned results, up to five:** relevant results divided by the
  number actually returned, capped at five. Empty positive searches score zero.
  This is shown alongside the fraction of the five slots filled.
- **Recall@5:** relevant results in the first five divided by all manually judged
  relevant agents. A query with seven relevant fixtures cannot reach full recall
  using only five result slots.
- **MRR@5:** reciprocal rank of the first relevant result, or zero if none appears
  in the first five. This is a truncated measure, not MRR over the full ranking.
- **No-match correctness:** whether designated no-match searches returned an empty
  list. They are excluded from the positive-query relevance averages.
- **Constraint violations:** top-five IDs manually annotated as failing required
  authentication, signature, transport or observation constraints.

Each positive query contributes equally to the macro averages. Duplicate result
IDs do not earn additional credit. Unjudged returned IDs do not count as relevant;
the report lists them so missing judgments can be inspected. A targeted distractor
can be the wrong capability without being a constraint violation. Matching a
publisher's declaration does not prove its task works, that an unsigned card is
unsafe, or that a no-auth declaration means an account will never be needed.

These fixtures are a regression set, not a private holdout. Any future additions
or changed judgments must increment the benchmark version and publish the reason.

## Replay a frozen live search sample

An optional live sample should be clearly labelled with its capture time and
ranking code digest. It is a one-time maintainer-judged observation, not a task
test or a claim that current live rankings will stay the same.

The scorer is also an importable standard-library function:

```python
from run_benchmark import evaluate_rankings
report = evaluate_rankings(cases, baseline_results, recommendation_results)
```

`cases` uses the same query/judgment shape as `fixtures.json`. Both result maps
use query IDs as keys and ordered listing ID arrays as values. API result objects
of the form `{"items": [{"id": 123}]}` are accepted too. Missing captures and
duplicate query IDs raise errors; an absent response cannot look like a successful
no-match decision. For example:

```json
{
  "metadata": {
    "captured_at": "2026-10-20T12:00:00+00:00",
    "candidate_snapshot_sha256": "hash-of-public-candidate-snapshot",
    "ranking_module_sha256": "hash-of-ranking-module",
    "selection_method": "Manually selected capabilities and distractors, not a random sample"
  },
  "cases": [{
    "id": "pdf-example",
    "q": "generate a PDF",
    "requirements": {},
    "judgments": {
      "relevant_ids": [123],
      "unacceptable_ids": [456],
      "constraint_ineligible_ids": [],
      "no_match_expected": false,
      "rationale": "123 declares PDF creation; 456 only fills existing forms"
    }
  }],
  "baseline_results": {"pdf-example": [456]},
  "recommendation_results": {"pdf-example": [123]}
}
```

Save a capture in that shape, then run:

```console
python run_benchmark.py --captures live-capture.json --output live-report.json
```

Live samples should provide enough public provenance to review the judgments:
listing/profile links, skill names, captured observations and timestamps, plus
snapshot hashes. Keep full third-party descriptions/cards, personal contact data,
private claims, IPs and moderation notes out of the published capture. Use only
public listings. Do not assume this fixture's MIT license grants rights to
third-party card content. Manually label cases before examining which ranking wins.

The included `live-capture.json` and `live-report.json` are a separate, eight-query
sample against 2,164 public stored listings captured on 20 October 2026. The known
positive judgments were written from public skill declarations before these
rankings were run. They are incomplete: a returned listing outside those judgments
can also be relevant. Only known-positive hit@5 and MRR@5 are reported, alongside
individually judged distractors. Precision and recall are deliberately omitted.
These are search observations, not tests of the advertised tasks. Listing IDs,
names and card/profile links are provided to inspect the judgments. The full
candidate text is not redistributed. `capture_live.py` documents the selection
and capture procedure but requires the original candidate snapshot to rerank;
`run_benchmark.py --captures live-capture.json` replays the published scoring.

## License

The synthetic fixtures, benchmark code and documentation are MIT licensed; see
`LICENSE`. This grants no rights to any third-party Agent Card or task output.
