#!/usr/bin/env python3
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from regression import ObservationError, import_observation
parser = argparse.ArgumentParser(description="Import an observed match state as an immutable regression")
parser.add_argument("--input", required=True); parser.add_argument("--output", required=True)
args = parser.parse_args()
try:
    output = import_observation(args.input, args.output)
    print(f"Wrote immutable regression {output}")
except ObservationError as error:
    parser.exit(2, f"error: {error}\n")
