#!/usr/bin/env python3
"""Generate a deterministic JSONL decision-state corpus."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from scenario_generation import generate_corpus, write_corpus

parser = argparse.ArgumentParser(description="Generate reproducible independent football decision states")
parser.add_argument("--role", required=True, choices=("gk", "def", "mid", "fwd1", "fwd2"))
parser.add_argument("--scenario-set", required=True, help="family, transition, all, or comma-separated families")
parser.add_argument("--count", required=True, type=int)
parser.add_argument("--seed", required=True, type=int)
parser.add_argument("--output", required=True)
args = parser.parse_args()
rows = generate_corpus(args.role, args.scenario_set, args.count, args.seed)
write_corpus(rows, args.output)
print(f"Wrote {len(rows)} scenarios to {args.output}")

