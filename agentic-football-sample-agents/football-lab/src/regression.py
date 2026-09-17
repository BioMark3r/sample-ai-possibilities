"""Import and inspect permanent, offline real-match decision observations."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from validation import validate_scenario

ROLES = {"gk", "def", "mid", "fwd1", "fwd2"}


class ObservationError(ValueError):
    """An observation or regression file does not satisfy the lab contract."""


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate_observation(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["observation must be a JSON object"]
    errors: list[str] = []
    for field in ("observation_id", "role", "expected_behavior"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            errors.append(f"{field} must be a non-empty string")
    if value.get("role") not in ROLES:
        errors.append(f"role must be one of: {', '.join(sorted(ROLES))}")
    if not isinstance(value.get("controlled_player_id"), int):
        errors.append("controlled_player_id must be an integer")
    if not isinstance(value.get("match_id") or value.get("match_label"), str):
        errors.append("match_id or match_label must be a non-empty string")
    for field in ("observed_behavior", "notes", "observed_at"):
        if field in value and value[field] is not None and not isinstance(value[field], str):
            errors.append(f"{field} must be a string when present")
    if "tags" in value and (not isinstance(value["tags"], list) or
                            not all(isinstance(tag, str) for tag in value["tags"])):
        errors.append("tags must be an array of strings")
    payload = value.get("gameState")
    if not isinstance(payload, dict):
        errors.append("gameState must contain a LocalAgent-compatible payload object")
    else:
        errors.extend(f"gameState payload: {error}" for error in validate_scenario(payload))
        player = value.get("controlled_player_id")
        if isinstance(player, int) and player not in payload.get("myPlayers", []):
            errors.append("controlled_player_id must appear in gameState.myPlayers")
    score = value.get("score")
    if score is not None and (not isinstance(score, dict) or
                              not all(isinstance(score.get(side), int) for side in ("home", "away"))):
        errors.append("score must contain integer home and away values")
    return errors


def import_observation(input_path: str | Path, output_dir: str | Path) -> Path:
    path = Path(input_path)
    try:
        observation = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ObservationError(f"Could not load observation {path}: {error}") from error
    errors = validate_observation(observation)
    if errors:
        raise ObservationError("Invalid observation: " + "; ".join(errors))

    digest = hashlib.sha256(_canonical(observation).encode()).hexdigest()
    prefix = re.sub(r"[^a-z0-9]+", "-", observation["observation_id"].lower()).strip("-") or "observation"
    regression_id = f"{prefix}-{digest[:12]}"
    payload = observation["gameState"]
    game_time = observation.get("gameTime", payload["gameState"].get("gameTime"))
    row = {
        "schema_version": 1,
        "regression_id": regression_id,
        "digest": f"sha256:{digest}",
        "metadata": {
            "observation_id": observation["observation_id"],
            "match": observation.get("match_id") or observation.get("match_label"),
            "role": observation["role"],
            "controlled_player_id": observation["controlled_player_id"],
            "observed_at": observation.get("observed_at"),
            "gameTime": game_time,
            "score": observation.get("score", payload["gameState"].get("score")),
            "expected_behavior": observation["expected_behavior"],
            "observed_behavior": observation.get("observed_behavior"),
            "notes": observation.get("notes", ""),
            "tags": observation.get("tags", []),
        },
        "payload": payload,
    }
    output = Path(output_dir) / f"{regression_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_text(encoding="utf-8") != json.dumps(row, indent=2, ensure_ascii=False) + "\n":
            raise ObservationError(f"Refusing to overwrite immutable regression: {output}")
        return output
    output.write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def load_regression(path: str | Path) -> dict:
    try:
        row = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ObservationError(f"Could not load regression {path}: {error}") from error
    if not isinstance(row, dict) or not isinstance(row.get("metadata"), dict):
        raise ObservationError("Regression must contain metadata and payload objects")
    errors = validate_scenario(row.get("payload"))
    if errors:
        raise ObservationError("Invalid regression payload: " + "; ".join(errors))
    return row


def inspect_regression(path: str | Path) -> dict:
    row = load_regression(path)
    metadata, payload = row["metadata"], row["payload"]
    state, team_id = payload["gameState"], payload.get("teamId", 0)
    own = "home" if team_id == 0 else "away"
    controlled_id = metadata["controlled_player_id"]
    controlled = next((p for p in state["players"] if p.get("teamCode") == own and
                       p.get("agentId") == f"agentId_{controlled_id}"), None)
    if controlled is None:
        raise ObservationError("Controlled player is absent from gameState.players")
    origin = controlled["position"]
    distance = lambda p: math.hypot(p["position"]["x"] - origin["x"], p["position"]["y"] - origin["y"])
    players = state["players"]
    opponents = sorted((p for p in players if p.get("teamCode") != own), key=distance)
    teammates = sorted((p for p in players if p.get("teamCode") == own and p is not controlled), key=distance)
    nearest = lambda entries: [{"player_id": p.get("agentId"), "distance": round(distance(p), 2)} for p in entries[:3]]
    ball = state["ball"]
    bx = ball["position"]["x"]
    pressure_distance = distance(opponents[0]) if opponents else None
    pressure = "unknown" if pressure_distance is None else "high" if pressure_distance <= 4 else "medium" if pressure_distance <= 10 else "low"
    possession = "free" if ball.get("isFree") or not ball.get("possessionAgentId") else \
        ("own" if any(p.get("teamCode") == own and p.get("agentId") == ball["possessionAgentId"] for p in players) else "opponent")
    score = metadata.get("score") or state.get("score") or {}
    own_score, other_score = (score.get("home"), score.get("away")) if own == "home" else (score.get("away"), score.get("home"))
    score_state = "unknown" if None in (own_score, other_score) else "level" if own_score == other_score else "leading" if own_score > other_score else "trailing"
    return {
        "regression_id": row.get("regression_id"), "role": metadata.get("role"),
        "possession": possession, "score": score, "score_state": score_state,
        "ball_position": ball["position"], "ball_zone": "defensive" if bx < -18 else "attacking" if bx > 18 else "middle",
        "nearest_opponents": nearest(opponents), "nearest_teammates": nearest(teammates),
        "pressure_level": pressure, "distance_to_attacking_goal": round(math.hypot((55 if own == "home" else -55) - origin["x"], origin["y"]), 2),
        "context": {key: metadata.get(key) for key in ("match", "observed_at", "gameTime", "tags")},
        "expected_behavior": metadata.get("expected_behavior"), "observed_behavior": metadata.get("observed_behavior"),
        "notes": metadata.get("notes"),
    }
