#!/usr/bin/env python3
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from regression import ObservationError, load_regression
from runner import LocalAgent
parser = argparse.ArgumentParser(description="Optionally replay an observed regression through a stock LocalAgent")
parser.add_argument("--scenario", required=True); parser.add_argument("--team", default="balanced")
args = parser.parse_args()
try:
    row = load_regression(args.scenario)
    result = LocalAgent(args.team, row["metadata"]["role"]).run(row["payload"], scenario_name=row["regression_id"])
except Exception as error:
    parser.exit(1, f"LIVE REPLAY FAILED (regression remains valid): {type(error).__name__}: {error}\n")
print(result.to_json())
if result.exception:
    parser.exit(1, f"LIVE REPLAY FAILED (regression remains valid): {result.exception}\n")
raise SystemExit(0 if result.valid_action else 1)
