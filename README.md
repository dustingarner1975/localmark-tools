# LocalMark tools

Open-source tools for [LocalMark](https://localmark.ai).

- [Agent Finder](https://dustingarner1975.github.io/localmark-tools/) is a static browser app that searches and verifies agents through LocalMark’s live API.
- `localmark-client` is a dependency-free Python client and command-line tool.

## Install the Python client

```sh
python -m pip install git+https://github.com/dustingarner1975/localmark-tools.git
localmark search weather --card-hours 24 --a2a-hours 24 --tls
localmark verify agent.example.com/a2a
localmark gate agent.example.com/a2a --card-hours 24 --a2a-hours 24 --tls
```

`gate` uses stored observations only. It exits 0 when all requested evidence passes, 2 when evidence is absent or stale, and 1 on an input or request error. It does not run an agent task or send payment.

## Python example

```python
from localmark_client import LocalMarkClient
client = LocalMarkClient()
results = client.search("weather", checked_within_hours=24,
                        a2a_response_within_hours=24, tls_reachable=True)
print(results["items"])
```

## Run Agent Finder locally

```sh
python -m http.server 8080 --directory docs
```

The app calls only LocalMark’s public read-only API and keeps no second agent index. Publisher card content belongs to its publishers. The client code is MIT licensed; LocalMark’s observations have a separate [CC BY 4.0 data licence](https://localmark.ai/data). See the [API guide](https://localmark.ai/for-agents).
