"""Find a shortlist and read a plan; deliberately never invoke an agent task."""

from pathlib import Path
from localmark_client import LocalMarkClient

client = LocalMarkClient()
shortlist = client.recommend(policy=Path(__file__).with_name("pdf-policy.json"))
for candidate in shortlist.get("items", []):
    print(candidate["name"], candidate["recommendation"]["reasons"])
    print(client.connection_plan(candidate["id"]))
    # Review evidence, auth requirements, capability fit and explicit task
    # authorization before making a separate connection in your own code.
