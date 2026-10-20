"""Command line access to public LocalMark evidence."""

import argparse
import json
import sys

from .client import LocalMarkClient, LocalMarkError


def main(argv=None):
    parser = argparse.ArgumentParser(prog="localmark", description="Inspect public A2A Agent Card evidence")
    parser.add_argument("--base-url", default="https://localmark.ai", help="LocalMark API origin")
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search", help="Search with optional evidence filters")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--skill")
    search.add_argument("--card-hours", type=int, dest="checked_within_hours")
    search.add_argument("--a2a-hours", type=int, dest="a2a_response_within_hours")
    search.add_argument("--tls", action="store_true")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    commands.add_parser("health", help="Check LocalMark availability")
    verify = commands.add_parser("verify", help="Inspect known evidence for a card, endpoint, or domain")
    verify.add_argument("target")
    agent = commands.add_parser("agent", help="Fetch an agent record")
    agent.add_argument("id", type=int)
    check = commands.add_parser("check-card", help="Perform a bounded read-only Agent Card check")
    check.add_argument("url")
    gate = commands.add_parser("gate", help="Exit 0 only when stored evidence meets your requirements")
    gate.add_argument("target", help="Card URL, endpoint URL, or domain")
    gate.add_argument("--card-hours", type=int, default=24)
    gate.add_argument("--a2a-hours", type=int)
    gate.add_argument("--tls", action="store_true")
    gate.add_argument("--signature", action="store_true")
    args = parser.parse_args(argv)
    client = LocalMarkClient(args.base_url)
    try:
        if args.command == "search":
            result = client.search(args.query, skill=args.skill,
                checked_within_hours=args.checked_within_hours,
                a2a_response_within_hours=args.a2a_response_within_hours,
                tls_reachable=True if args.tls else None, limit=args.limit, offset=args.offset)
        elif args.command == "verify":
            result = client.verify(args.target)
        elif args.command == "agent":
            result = client.agent(args.id)
        elif args.command == "check-card":
            result = client.check_card(args.url)
        elif args.command == "gate":
            result = client.gate(args.target, card_hours=args.card_hours,
                                 a2a_hours=args.a2a_hours, tls=args.tls,
                                 signature=args.signature)
        else:
            result = client.health()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 2 if args.command == "gate" and not result["passed"] else 0
    except (LocalMarkError, ValueError) as exc:
        print(f"localmark: {exc}", file=sys.stderr)
        if isinstance(exc, LocalMarkError) and exc.retry_after:
            print(f"Retry after {exc.retry_after} seconds", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
