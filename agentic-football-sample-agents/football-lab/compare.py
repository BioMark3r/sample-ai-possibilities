#!/usr/bin/env python3
"""Run multiple configurations over one immutable in-memory corpus."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from adapters import TEAMS
from analysis import compare_decisions
from benchmarking import run_benchmark
from scenario_generation import load_corpus

parser = argparse.ArgumentParser(description="Compare stock configurations on identical scenarios")
parser.add_argument("--scenario-set", required=True)
parser.add_argument("--config", action="append", required=True, help="TEAM:ROLE (repeat at least twice)")
parser.add_argument("--runs", type=int, default=1)
parser.add_argument("--database", default="results/football_lab.sqlite")
parser.add_argument("--output", default="results/comparison.json")
args = parser.parse_args()
if len(args.config) < 2:
    parser.error("provide --config at least twice")
configs = []
for value in args.config:
    try: team, role = value.split(":", 1)
    except ValueError: parser.error(f"invalid config {value!r}; expected TEAM:ROLE")
    if team not in TEAMS: parser.error(f"unknown team {team!r}")
    configs.append((team, role))
corpus = load_corpus(args.scenario_set)  # load once; every runner receives the same object
benchmarks = [run_benchmark(team, role, corpus, args.runs, corpus_path=args.scenario_set,
                            database=args.database) for team, role in configs]
comparisons = [{"left_benchmark_id": benchmarks[0]["benchmark_id"],
                "right_benchmark_id": item["benchmark_id"],
                "metrics": compare_decisions(benchmarks[0]["decisions"], item["decisions"])}
               for item in benchmarks[1:]]
document = {"schema_version": 1, "benchmarks": [{k: b[k] for k in ("benchmark_id", "team", "role", "summary")} for b in benchmarks],
            "comparisons": comparisons}
path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
print(json.dumps(document, indent=2))

