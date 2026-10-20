# LocalMark tools

A small, open-source extension to [LocalMark](https://localmark.ai):

- [Agent Finder](https://localmark.ai/for-agents), a browser app in `docs/` that searches the live LocalMark API and checks a card, endpoint, or domain.
- `localmark-client`, a dependency-free Python client and command-line tool in `src/`.

The app does not maintain another directory or run third-party tasks. It displays the publisher's declared card information alongside LocalMark's observed checks. A recent read-only A2A response is evidence of protocol behaviour, not a guarantee of identity, quality, or task performance.

## Run locally

Serve `docs/` with any static file server, for example:

```sh
python -m http.server 8080 --directory docs
```

Open `http://localhost:8080`. The app calls only `https://localmark.ai` for public read-only data. Search results and verification answers are not stored by this app.

## Python client

```sh
python -m pip install .
localmark search weather --card-hours 24 --a2a-hours 24 --tls
localmark verify agent.example.com/a2a
localmark gate agent.example.com/a2a --card-hours 24 --a2a-hours 24 --tls
```

```python
from localmark_client import LocalMarkClient

client = LocalMarkClient()
items = client.search("weather", checked_within_hours=24,
    a2a_response_within_hours=24, tls_reachable=True)["items"]
```

See [LocalMark's API guide](https://localmark.ai/for-agents) and [OpenAPI](https://localmark.ai/openapi.json). Public endpoints may be rate limited. The software is MIT licensed; LocalMark's observation data has a separate [CC BY 4.0 licence](https://localmark.ai/data). Publisher-supplied card content is not licensed by this repository.

`gate` uses stored observations and exits `0` when every requested condition passes, `2` when evidence is absent or stale, and `1` for a request or input error. It is suitable for a CI preflight check, not for deciding whether to trust an agent's outputs or whether to send money.
