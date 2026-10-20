#!/usr/bin/env python3
"""Reproduce LocalMark reports from already-downloaded public daily snapshots."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json

from research_reports import generate_reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Directory containing YYYY-MM-DD.json manifests and matching .jsonl.gz files")
    parser.add_argument("--as-of", help="Use the published report generated_at time for repeatable calendar status and timestamps")
    args = parser.parse_args()
    if not args.input.is_dir():
        parser.error("input must be an existing directory of downloaded snapshots")
    now = None
    if args.as_of:
        try:
            now = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
            if now.tzinfo is None:
                raise ValueError("Timezone required")
            now = now.astimezone(timezone.utc)
        except ValueError:
            parser.error("as-of must be an ISO timestamp with a timezone")
    result = generate_reports(args.input, now=now)
    print(json.dumps({"output_directory": str(args.input / "reports"), **result}, indent=2))


if __name__ == "__main__":
    main()
