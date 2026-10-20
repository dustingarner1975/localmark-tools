"""Command line access to public LocalMark evidence."""

import argparse
import json
import sys

from .client import LocalMarkClient, LocalMarkError


def main(argv=None):
    parser = argparse.ArgumentParser(prog="localmark", description="Inspect public A2A Agent Card evidence")
    parser.add_argument("--base-url", default="https://localmark.ai", help="LocalMark API origin")
    parser.add_argument("--project-id", help="Optional random UUIDv4 for aggregate project-use metrics; never a secret")
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search", help="Search with optional evidence filters")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--skill")
    search.add_argument("--card-hours", type=int, dest="checked_within_hours")
    search.add_argument("--a2a-hours", type=int, dest="a2a_response_within_hours")
    search.add_argument("--tls", action="store_true")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    recommend = commands.add_parser("recommend", help="Find a capability shortlist with matching reasons and caveats")
    recommend.add_argument("query", nargs="?", help="The capability or job you need, up to 200 characters")
    recommend.add_argument("--policy", help="Saved JSON requirement file; explicit flags override it")
    recommend.add_argument("--auth", choices=("none", "declared"), help="Authentication declared by the publisher")
    recommend.add_argument("--signature", choices=("verified",))
    recommend.add_argument("--protocol", choices=("JSONRPC", "HTTP+JSON", "GRPC"))
    recommend.add_argument("--card-hours", type=int, dest="checked_within_hours")
    recommend.add_argument("--a2a-hours", type=int, dest="a2a_response_within_hours")
    recommend.add_argument("--tls", action=argparse.BooleanOptionalAction, default=None)
    recommend.add_argument("--network", help="Payment network, such as eip155:8453")
    recommend.add_argument("--asset", help="Payment asset identifier, such as a token contract")
    recommend.add_argument("--max-amount", help="Maximum price in asset units (e.g. 0.05 USDC); requires --network and --asset")
    recommend.add_argument("--limit", type=int)
    recommend.add_argument("--offset", type=int)
    plan = commands.add_parser("plan", help="Read connection instructions without invoking the agent")
    plan.add_argument("target", help="LocalMark agent ID, card URL, endpoint URL or domain")
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
    try:
        client = LocalMarkClient(args.base_url, project_id=args.project_id)
        if args.command == "search":
            result = client.search(args.query, skill=args.skill,
                checked_within_hours=args.checked_within_hours,
                a2a_response_within_hours=args.a2a_response_within_hours,
                tls_reachable=True if args.tls else None, limit=args.limit, offset=args.offset)
        elif args.command == "recommend":
            result = client.recommend(args.query, policy=args.policy, auth=args.auth, signature=args.signature,
                protocol=args.protocol, checked_within_hours=args.checked_within_hours,
                a2a_response_within_hours=args.a2a_response_within_hours,
                tls_reachable=args.tls, network=args.network,
                asset=args.asset, max_amount=args.max_amount, limit=args.limit,
                offset=args.offset)
        elif args.command == "plan":
            result = client.connection_plan(args.target)
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
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 2 if args.command == "gate" and not result["passed"] else 0
    except (LocalMarkError, ValueError) as exc:
        print(f"localmark: {exc}", file=sys.stderr)
        if isinstance(exc, LocalMarkError) and exc.retry_after:
            print(f"Retry after {exc.retry_after} seconds", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
