# Prospective search evaluation — awaiting external judgments

Version: `prospective-2026-10-20-v1`. Frozen 20 October 2026 at 08:13:01 UTC.
These 20 new task queries were authored after the released capability ranker.
They have not been sent to it for tuning or used to adjust its vocabulary.
They are **maintainer-authored**, not independently authored. No external
relevance judgments or prospective scores have been collected at publication.

The existing development fixture and its committed report remain unchanged.
This prospective set is separate. Once any future ranker is tuned using these
queries or judgments, it becomes development data for that version; freeze a
fresh set before making the next prospective claim.

## Files and integrity

- `queries.json`: frozen task text and explicit evidence requirements.
- `manifest.json`: SHA-256 values, freeze time and ranker source/version anchor.
- `status.json`: explicitly unscored publication status.
- `capture.py`: public LocalMark recommendation capture; no publisher task,
  payment, card recheck or endpoint probe is performed.
- `evaluate.py`: create a blinded candidate pool and score external judgments.
- `judgment-template.json`: intentionally incomplete; never counts as a judge.
- `*.schema.json`: JSON Schemas for queries, ranking captures and judgments.
- `test_evaluate.py`: isolated scoring tests, unrelated to the frozen queries.

Code is MIT licensed under the repository licence. LocalMark observations use
CC BY 4.0. Publisher names and short declaration excerpts remain the publisher’s
content; LocalMark grants no rights in them. Keep private contact details,
tokens, claim data and private URLs out of captures and judgments.

## Capture first; keep ranking information away from judges

Use Python 3.10 or newer. The scripts have no dependencies. Do not run a capture
to tune the ranker and then describe the same query set as held out.

```sh
python capture.py --system candidate-a --output candidate-a.json
```

Capture another version against the same frozen queries and as nearly the same
corpus/time as possible, or provide its output using `rankings.schema.json`.
LocalMark uses a changing live corpus, so sequential live captures cannot prove
that ranking alone caused a difference. Publish capture times, corpus identity,
requirements, error cases, source version and any differences. For a controlled
comparison, use the same permitted saved corpus and observation clock.

The system codes should not tell judges which implementation they represent.
Use a separate coordinator who is not a judge to combine captures:

```sh
python evaluate.py --rankings candidate-a.json --rankings candidate-b.json \
  --pool-output blind-pool.json --output unjudged-status.json
```

Give judges **only** the frozen queries, grading instructions and the unordered
`blind-pool.json`, with publisher declarations/evidence. Do not give them ranking
files, scores, system identities or result ordering. The pool sorts by agent ID,
which is unrelated to ranking. It includes the union of each system’s top five.
Judges may follow source card/profile links for evidence, but should not run the
same search to discover the system rankings. Disclose any accidental exposure.

## External judging

Each judge copies `judgment-template.json`, chooses a pseudonymous code, declares
their relationship/conflicts, and truthfully sets the two attestations. Anyone
who developed or tuned the ranker may provide feedback but does not count toward
the external-judge minimum. Independence and blinding are self-attested, not
verified identities. A contributor can decline public attribution.

For each query, grade **every pooled candidate** and record a short reason:

- **0:** unrelated operation, or evidence contradicts an explicit requirement.
- **1:** partial, related or uncertain operation; more provider information is
  required before this would be an explicit capability match.
- **2:** explicitly declares the requested operation and the supplied evidence
  meets the query’s stated selection requirements.

Check evidence at the capture time when available; do not treat a later outage
as the earlier ranking’s error. A missing observation is not a positive result.
No declaration, signature or probe result establishes task quality or safety.
Use an optional `evidence_url` for the public source. Mark `complete_pool: true`
only after every candidate in that query’s pool has been graded. A query with an
empty pool still needs two judges to explicitly confirm that they reviewed it.

Submit permitted JSON and your conflict disclosure through a pull request to
[the developer-tools repository](https://github.com/dustingarner1975/localmark-tools).
Do not send unsolicited email to listed publishers or copy their contact data.

## Score and publish the inputs

```sh
python evaluate.py --rankings candidate-a.json --rankings candidate-b.json \
  --judgments judge-one.json --judgments judge-two.json --output evaluation.json
python -m unittest discover -s . -p test_evaluate.py -v
```

At least two distinct external judges, each self-attesting independence and
blinding, must completely cover a query’s pooled candidates before it is scored.
Unjudged queries remain unscored; they are not silently dropped into a complete
headline. Conflicting grades are retained, and mean grades determine pooled
nDCG@5. Binary relevance for precision and reciprocal rank means mean grade ≥ 1.
Precision has a fixed denominator of five, even for a short list. Only queries
with at least one pooled relevant candidate contribute to aggregate precision
and reciprocal rank. An error or missing capture remains an error/missing case,
never a successful no-match case. No global recall is claimed because relevance
outside the retrieved pool is unknown.

Publish the frozen queries, manifest, ranker/corpus references, dated captures,
permitted judgment files, conflicts, completeness, disagreements and report
together. Partial judgment reports do not establish a winner. A public result
must state that the query set was maintainer-authored and that independence was
self-reported. Do not call the process an independent audit or certification.
