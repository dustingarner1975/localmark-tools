# Reproduce State of the agent web reports

The adjacent `research_reports.py` is the same public-snapshot aggregation module
used by LocalMark. `source-manifest.json` records its SHA-256. It is copied from
the deployed source; the CLI wrapper does not change the counting rules.
Python 3.10 or newer, standard library only. No network request is made.

1. Read [the public snapshot index](https://localmark.ai/data/index.json).
2. Download each available daily `YYYY-MM-DD.json` manifest and its matching
   `YYYY-MM-DD.jsonl.gz` snapshot for the month into a new local folder. Use the
   actual download links in the index, not inferred filenames.
3. Use the report’s `generated_at` value as `--as-of` if you want the same
   month-to-date/closed-month classification and generation timestamp.

```sh
python research/reproduce.py --input downloaded-snapshots \
  --as-of 2026-10-20T08:00:00Z
```

Generated JSON is written under `downloaded-snapshots/reports/`. The module
verifies every gzip SHA-256 and record count against its daily manifest before
publishing a report. An existing closed report is left in place; start with a
new directory when reproducing a different observation window. A report is
complete for its available snapshots, not proof that every calendar day exists.
Compare the report’s source date list with the snapshot index.

Counts describe public records in those snapshots: distinct publisher domains,
verified card signatures, confirmed read-only A2A responses, TLS evidence and
ownership claims. Tags are ranked by distinct publishers. A growth in listed
records includes discovery, removals, failures and duplicate consolidation; it
does not measure newly created agents. Task tests are a separate opt-in signal.
The dataset is not an Internet-wide census, continuous-uptime measurement or
task-performance study. An open calendar month is labelled month to date; a closed calendar month can
also have incomplete snapshot coverage. Coverage begins on the first available snapshot.

Code is MIT licensed. Cite LocalMark observations as **Data: LocalMark
(localmark.ai), CC BY 4.0**, including the snapshot dates. Publisher content is
outside that licence. Downloaded old snapshots may include listings removed
from later releases, so check the current directory before redistributing.

See [the report collection](https://localmark.ai/reports),
[dataset notes](https://localmark.ai/data) and
[the source repository](https://github.com/dustingarner1975/localmark-tools).
