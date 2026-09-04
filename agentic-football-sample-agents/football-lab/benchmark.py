#!/usr/bin/env python3
"""Run one stock team/role benchmark."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from adapters import TEAMS
from benchmarking import run_benchmark

parser = argparse.ArgumentParser(description="Benchmark one stock team/role over a scenario JSONL corpus")
parser.add_argument("--team", required=True, choices=tuple(TEAMS))
parser.add_argument("--agent", required=True, choices=("gk", "def", "mid", "fwd1", "fwd2"))
parser.add_argument("--scenarios", required=True)
parser.add_argument("--runs", type=int, default=1)
parser.add_argument("--output", required=True)
parser.add_argument("--database", default="results/football_lab.sqlite")
args = parser.parse_args()
result = run_benchmark(args.team, args.agent, args.scenarios, args.runs,
                       output=args.output, database=args.database)
print(json.dumps({"benchmark_id": result["benchmark_id"], "summary": result["summary"]}, indent=2))

