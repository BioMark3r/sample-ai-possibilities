#!/usr/bin/env python3
"""Create an editable observation from an existing LocalAgent scenario."""
import argparse, json
from pathlib import Path
parser = argparse.ArgumentParser(description="Create a Week 2 observation template around a scenario payload")
parser.add_argument("--scenario", required=True, help="LocalAgent-compatible scenario JSON to copy")
parser.add_argument("--output", required=True); parser.add_argument("--observation-id", required=True)
parser.add_argument("--match", required=True); parser.add_argument("--role", required=True, choices=("gk","def","mid","fwd1","fwd2"))
parser.add_argument("--controlled-player-id", required=True, type=int)
args = parser.parse_args()
payload = json.loads(Path(args.scenario).read_text())
value = {"observation_id": args.observation_id, "match_label": args.match, "role": args.role,
         "controlled_player_id": args.controlled_player_id, "observed_at": None,
         "gameTime": payload.get("gameState", {}).get("gameTime"),
         "score": payload.get("gameState", {}).get("score"), "gameState": payload,
         "expected_behavior": "REPLACE: what should the player do?", "observed_behavior": None,
         "notes": "REPLACE: source/log reference and reconstruction assumptions", "tags": ["week2"]}
out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
if out.exists(): parser.error(f"refusing to overwrite {out}")
out.write_text(json.dumps(value, indent=2) + "\n"); print(f"Wrote editable observation template {out}")
