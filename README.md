# LocalMark tools

Open-source tools for [LocalMark](https://localmark.ai).

- [Agent Finder](https://dustingarner1975.github.io/localmark-tools/) is a static browser app that searches and verifies agents through LocalMark’s live API.
- `localmark-client` is a dependency-free Python client and command-line tool.

## Install the Python client

Requires **Python 3.10 or newer**. Run the command below in a terminal; it installs the `localmark` command and Python library. No API key is needed.

```sh
python -m pip install https://localmark.ai/static/downloads/localmark_client-0.3.0-py3-none-any.whl
```

Then search or inspect a real agent address:

```sh
localmark search weather --card-hours 24 --a2a-hours 24 --tls
localmark recommend "extract text from PDF documents" --card-hours 24 --tls
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

## Run Agent Finder locally

Clone or download this repository first, then run the following from its folder:

```sh
python -m http.server 8080 --directory docs
```

Open <http://localhost:8080>. For the hosted version, use [Agent Finder](https://dustingarner1975.github.io/localmark-tools/) without installing anything. It displays LocalMark’s stored observations, not a new live probe of the publisher. Cards are scheduled for a fresh fetch every two hours, and each result shows its observation time. Card reachability, endpoint TLS, A2A responses and signatures are separate signals; none guarantees task performance or provider identity.

The app calls only LocalMark’s public read-only API and keeps no second agent index. Publisher card content belongs to its publishers. The client code is MIT licensed; LocalMark’s observations have a separate [CC BY 4.0 data licence](https://localmark.ai/data). See the [API guide](https://localmark.ai/for-agents).

## Public search benchmark

The [benchmark source and methodology](benchmark/README.md) include the fixed synthetic cards, manual relevance judgments, exact ranking code, results, and a separate observed live sample. See the [public benchmark page](https://localmark.ai/benchmark). This is a maintainer-authored development set, not an independent assessment or a test of agent tasks. Replay it offline with `python benchmark/run_benchmark.py`; the Python 3.10 and 3.12 checks reproduce the committed report and test its scorer.
