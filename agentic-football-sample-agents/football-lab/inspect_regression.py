#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from regression import ObservationError, inspect_regression
parser = argparse.ArgumentParser(description="Inspect a regression without AWS or model calls")
parser.add_argument("--scenario", required=True)
args = parser.parse_args()
try: print(json.dumps(inspect_regression(args.scenario), indent=2))
except ObservationError as error: parser.exit(2, f"error: {error}\n")
