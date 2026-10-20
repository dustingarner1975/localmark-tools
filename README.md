# LocalMark tools

Open-source tools for [LocalMark](https://localmark.ai).

- [Agent Finder](https://dustingarner1975.github.io/localmark-tools/) is a static browser app that searches and verifies agents through LocalMark’s live API.
- `localmark-client` is a dependency-free Python client and command-line tool.

## Install the Python client

Requires **Python 3.10 or newer**. Run the command below in a terminal; it installs the `localmark` command and Python library. No API key is needed.

```sh
python -m pip install https://localmark.ai/static/downloads/localmark_client-0.4.1-py3-none-any.whl
```

Then search or inspect a real agent address:

```sh
localmark search weather --card-hours 24 --a2a-hours 24 --tls
localmark recommend "extract text from PDF documents" --card-hours 24 --tls
localmark plan agent.example.com/a2a
localmark verify agent.example.com/a2a
localmark gate agent.example.com/a2a --card-hours 24 --a2a-hours 24 --tls
```

`agent.example.com` is a placeholder; replace it with a real card URL, endpoint or domain. `verify` accepts publisher domains and may return several listings. `gate` needs evidence for an individual agent: a publisher summary alone cannot pass it.

To install directly from the repository instead, install Git and run `python -m pip install git+https://github.com/dustingarner1975/localmark-tools.git`.

`gate` uses stored observations only. It exits 0 when all requested evidence passes, 2 when evidence is absent or stale, and 1 on an input or request error. It does not run an agent task or send payment.

## Python example

```python
from localmark_client import LocalMarkClient
client = LocalMarkClient()
results = client.search("weather", checked_within_hours=24,
                        a2a_response_within_hours=24, tls_reachable=True)
print(results["items"])
```

## Capability recommendations

`recommend` uses the same ranking as the LocalMark website and MCP tool. It returns a shortlist with matching capabilities, reasons, caveats, and the observation times. Results use stored evidence; a high score is a capability match, not a guarantee of task quality or safety. If no agents meet your requirements, `items` is empty. An empty shortlist means LocalMark has no matching evidence; it is not a finding that other agents are unsafe.

```sh
localmark recommend "weather forecast" --auth none --protocol JSONRPC --card-hours 24 --a2a-hours 24
localmark recommend "PDF forms" --signature verified --limit 5
```

```python
results = client.recommend("extract text from PDF documents", auth="none",
                           checked_within_hours=24, tls_reachable=True)
for agent in results["items"]:
    print(agent["name"], agent["recommendation"]["reasons"],
          agent["recommendation"]["caveats"])
```

Filters are `auth` (`none` or `declared`), `signature` (`verified`), `protocol` (`JSONRPC`, `HTTP+JSON` or `GRPC`), card/A2A observation age (1–168 hours), TLS reachability, payment `network`, `asset`, and `max_amount`. A price ceiling requires a network **and** an asset and uses human-readable asset units: `max_amount="0.05"` means 0.05 USDC for a USDC asset. Unknown asset decimals are rejected. Prices in different currencies are never compared as if they were equivalent. CLI equivalents are `--network`, `--asset`, and `--max-amount`. The result echoes `query`, `interpreted_query`, and applied `requirements`, includes `total_matches`, `limit`, and `offset` for pagination, plus `ranking_version` and `scope` for interpretation.

Explore the public [search benchmark](https://localmark.ai/benchmark) to see the published cases and current results. The benchmark measures retrieval from declared capabilities and stored evidence; it does not execute tasks.

## Save requirements and read a connection plan

Save a JSON file containing the same recommendation fields used by the API:

```json
{
  "q": "extract text from PDF documents",
  "checked_within_hours": 24,
  "tls_reachable": true,
  "limit": 5
}
```

```sh
localmark recommend --policy pdf-policy.json
localmark recommend "fill PDF forms" --policy pdf-policy.json --limit 3
localmark plan 123
```

An explicit command-line query or flag overrides that saved field. Use
`--no-tls` to override a saved TLS filter off. The query
may be left out of the file when provided separately. Unknown fields, duplicate
JSON keys, invalid types and files larger than 64 KiB are rejected. Only public
search requirements are supported: keep passwords, tokens, headers and payment
keys out of policies. `auth: "none"` means no authentication is declared;
it does not guarantee account-free access.

```python
from localmark_client import LocalMarkClient, load_policy

client = LocalMarkClient()
shortlist = client.recommend(policy=load_policy("pdf-policy.json"))
for agent in shortlist["items"]:
    plan = client.connection_plan(agent["id"])
    print(plan["interfaces"], plan["authentication"], plan["evidence"])
```

`plan` returns advertised endpoints, protocol versions, authentication scheme
metadata, modes, skill names and stored evidence. It accepts an individual
LocalMark ID, card URL, endpoint or domain; a publisher domain may be ambiguous.
It never returns keys and does not connect to the publisher. Recheck evidence,
review the publisher's documentation, obtain any required credentials separately
and authorize the actual task before calling an endpoint. Plans and policies
do not authorize tasks, payments, automatic failover or credential sharing.

## Check cards and dependencies in GitHub Actions

This repository is also a reusable, dependency-free composite action. It uses
Python 3.10 or newer already available on the runner and the client code at the
action's selected revision. It downloads no shell installer and installs no
packages. Pin the action to a reviewed full commit SHA in production.

```yaml
permissions:
  contents: read
jobs:
  dependency-check:
    runs-on: ubuntu-latest
    steps:
      # Replace main with a reviewed full commit SHA.
      - uses: dustingarner1975/localmark-tools@main
        with:
          target: https://agent.example.com/a2a
          card-hours: '24'
          a2a-hours: '24'
          tls: 'true'
          signature: 'false'
```

The default `mode: stored` requires an individual listed agent, successful fresh
card evidence, and the requested TLS, A2A and signature checks. Unknown or stale
evidence fails the job. TLS evidence must be within `card-hours` when TLS is
required. Set `mode: check-card` with the full `/.well-known/agent-card.json`
or legacy `/.well-known/agent.json` URL to run a bounded read-only card preflight
instead. That mode can validate an unlisted card but still requires structure,
fresh observation time and any requested checks. Both modes fail on API errors
and rate limits. No mode runs an agent task or sends payment. Use a scheduled
daily check rather than probing on every commit in a busy repository.

See [the CI example](examples/card-check.yml),
[policy and plan example](examples/recommend_and_plan.py) and
[double opt-in watch example](examples/opt-in-alerts.md).

## Opt-in change watches and alternatives

At [LocalMark watches](https://localmark.ai/watch), save an agent or capability
policy and confirm your email. LocalMark can notify you about availability,
changed requirements, risky card/payment changes and new matches. Suggested
alternatives are explained recommendations; they are never connected to
automatically. Only addresses whose owners opt in and confirm receive these
service messages. Every activated watch has private management/unsubscribe
links. Do not put these private links in a repository.

Applications can request a confirmation at `POST /api/v1/watch-subscriptions`
with `email`, explicit `consent: true`, and exactly one of `agent_id` or `policy`.
The generic 202 response does not reveal whether an address already subscribes.
See [the complete opt-in example](examples/opt-in-alerts.md).

## Optional project-use measurement

By default the client sends no project identifier. If you want to help count
repeat integrations, create a random UUIDv4 once (`python -c "import uuid;
print(uuid.uuid4())"`) and explicitly pass `LocalMarkClient(project_id="...")`
or the global `localmark --project-id UUID ...` option. This sends
`X-LocalMark-Project` with requests to LocalMark. It is a public, self-reported
identifier, never an API key, person, email, credential or authorization token.
Keep a separate ID for each project. LocalMark retains a keyed hash in daily
aggregate usage records for 90 days; it does not count these as verified unique
users. Omitting the option disables this measurement. No ID is generated or
stored automatically, and policy files do not accept it.

## Run Agent Finder locally

Clone or download this repository first, then run the following from its folder:

```sh
python -m http.server 8080 --directory docs
```

Open <http://localhost:8080>. For the hosted version, use [Agent Finder](https://dustingarner1975.github.io/localmark-tools/) without installing anything. It displays LocalMark’s stored observations, not a new live probe of the publisher. Cards are scheduled for a fresh fetch every two hours, and each result shows its observation time. Card reachability, endpoint TLS, A2A responses and signatures are separate signals; none guarantees task performance or provider identity.

The app calls only LocalMark’s public read-only API and keeps no second agent index. Publisher card content belongs to its publishers. The client code is MIT licensed; LocalMark’s observations have a separate [CC BY 4.0 data licence](https://localmark.ai/data). See the [API guide](https://localmark.ai/for-agents).

## Public search benchmark

The [benchmark source and methodology](benchmark/README.md) include the fixed synthetic cards, manual relevance judgments, exact ranking code, results, and a separate observed live sample. See the [public benchmark page](https://localmark.ai/benchmark). This is a maintainer-authored development set, not an independent assessment or a test of agent tasks. Replay it offline with `python benchmark/run_benchmark.py`; the Python 3.10 and 3.12 checks reproduce the committed report and test its scorer.

The separate [prospective evaluation package](benchmark/prospective-evaluation/README.md)
freezes new task queries and provides blinded-pool capture, judgment schemas and
a reproducible evaluator. It is **awaiting external judgments**; no independent
scores are claimed. [Participate in judging](https://localmark.ai/benchmark/participate).

## Capability guides and reproducible research

The [integration hub](https://localmark.ai/integrations) connects these tools with
[practical capability guides](https://localmark.ai/guides) for PDF extraction,
weather and payment verification. Each guide links to current recommendations
and explains relevant evidence, input/output, authentication and cost limits.

[State of the agent web reports](https://localmark.ai/reports) aggregate available
public daily snapshots and distinguish month-to-date from closed calendar months.
The [report reproduction module and CLI](research/README.md) are published here
with source checksums. They verify daily file hashes and record counts before
aggregating; no Internet-wide coverage or task-quality claim is implied.
