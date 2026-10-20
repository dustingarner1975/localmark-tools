# Opt in to change notifications

Use [LocalMark watches](https://localmark.ai/watch) to choose a listed agent or
save capability requirements. Enter your own address and confirm the email.
Nothing is activated until you confirm. Watches send service notifications;
they never run a task or pay a provider. Manage, renew or unsubscribe using
the private link in the messages. Keep confirmation and management links out
of source control, logs and public issues.

Applications can request the same double opt-in flow:

```python
import json
from urllib.request import Request, urlopen

payload = {
    "email": "you@example.com",  # Your address; never import publisher emails.
    "consent": True,  # Set only after that person explicitly opts in.
    "policy": {
        "q": "extract text from PDF documents",
        "checked_within_hours": 24,
        "tls_reachable": True,
        "limit": 5,
    },
    "events": ["requirements", "risk", "new_matches"],
}
request = Request("https://localmark.ai/api/v1/watch-subscriptions",
                  data=json.dumps(payload).encode(), method="POST",
                  headers={"Content-Type": "application/json", "Accept": "application/json"})
with urlopen(request, timeout=10) as response:
    print(response.status, json.load(response))  # Generic 202, no private token.
```

To watch a specific listing, replace `policy` with `"agent_id": 123` (use a real
LocalMark ID). Exactly one of `agent_id` and `policy` is required. Allowed events
are `availability`, `requirements`, `risk` and `new_matches`; relevance depends
on the watch type. Read [the live API documentation](https://localmark.ai/for-agents)
for current limits and retention. An email delivery is a notification about
stored evidence, not a guarantee that every change has been detected.
