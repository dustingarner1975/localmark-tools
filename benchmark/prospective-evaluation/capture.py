#!/usr/bin/env python3
"""Capture LocalMark rankings without invoking publishers; no grades or tuning."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from evaluate import ROOT, verify_queries, write


def capture(queries, system_id, base_url="https://localmark.ai", delay=1):
    origin = urlsplit(base_url)
    if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.path not in ("", "/") or origin.query or origin.fragment:
        raise ValueError("base_url must be an HTTPS origin without credentials or a path")
    if not system_id.strip() or len(system_id) > 80:
        raise ValueError("system_id must contain 1..80 characters")
    results = []
    for index,query in enumerate(queries["queries"]):
        if index:
            time.sleep(delay)
        params = {"q": query["query"], "limit": 5, **query["requirements"]}
        params = {key: str(value).lower() if isinstance(value,bool) else value for key,value in params.items()}
        url = base_url.rstrip("/")+"/api/v1/recommend?"+urlencode(params)
        request = Request(url, headers={"Accept":"application/json", "User-Agent":"LocalMark-prospective-evaluation/1"})
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise ValueError("Response exceeds 4 MB")
                report = json.loads(raw)
            candidates = []
            for item in report.get("items", [])[:5]:
                candidates.append({"agent_id": str(item["id"]), "name": item.get("name"),
                    "profile_url": "https://localmark.ai/agents/"+str(item["id"]), "card_url": item.get("card_url"),
                    "publisher_declared_excerpt": str(item.get("description") or "")[:300],
                    "declared_skills": [{"name": skill.get("name"), "description_excerpt": str(skill.get("description") or "")[:200], "tags": skill.get("tags", [])[:20]}
                                        for skill in item.get("capabilities", [])[:20]],
                    "evidence": {key:item.get(key) for key in ("last_verified", "signature_status", "read_only_a2a_probe", "endpoint_tls")},
                    "publisher_content_license": "None granted by LocalMark; see publisher card"})
            status = "needs_clarification" if report.get("status") == "needs_clarification" else "ok" if candidates else "empty"
            results.append({"query_id":query["id"], "status":status, "agent_ids":[row["agent_id"] for row in candidates],
                            "candidates":candidates, "ranking_version":report.get("ranking_version"), "generated_at":report.get("generated_at"),
                            "requirements":report.get("requirements",query["requirements"])})
        except (HTTPError, URLError, ValueError, TimeoutError) as exc:
            results.append({"query_id":query["id"], "status":"error", "agent_ids":[], "error":str(exc)[:200]})
    return {"system_id":system_id, "query_set_version":queries["version"], "captured_at":datetime.now(timezone.utc).isoformat(),
            "origin":base_url.rstrip("/"), "scope":"Stored directory recommendations only; no publisher task, payment or live endpoint probe.", "queries":results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", required=True, help="A stable blinded system code, e.g. candidate-a")
    parser.add_argument("--base-url", default="https://localmark.ai")
    parser.add_argument("--queries", default=str(ROOT/"queries.json"))
    parser.add_argument("--manifest", default=str(ROOT/"manifest.json"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = capture(verify_queries(args.queries,args.manifest), args.system, args.base_url)
    write(args.output,result)
    print("Captured",len(result["queries"]),"queries; external judgments are still required.")


if __name__ == "__main__":
    main()
