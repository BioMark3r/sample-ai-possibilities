#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from runner import format_text, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Invoke a stock Agentic Football agent locally")
    parser.add_argument("--team", default="balanced")
    parser.add_argument("--agent", required=True, choices=("gk", "def", "mid", "fwd1", "fwd2"))
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--quiet", action="store_true", help="suppress progress messages")
    args = parser.parse_args(argv)

    def report_status(message: str) -> None:
        print(f"[football-lab] {message}", file=sys.stderr, flush=True)

    result = run(args.team, args.agent, args.scenario,
                 status_callback=None if args.quiet else report_status)
    print(result.to_json() if args.as_json else format_text(result))
    return 0 if result.valid_action and result.exception is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
