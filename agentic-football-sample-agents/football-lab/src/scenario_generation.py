"""Deterministic, independent synthetic decision-state generation."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

FAMILIES = ("possession", "transition_attack", "transition_defense", "under_pressure",
            "shooting_opportunity", "loose_ball", "defensive_shape")
ROLE_IDS = {"gk": 0, "def": 1, "mid": 2, "fwd1": 3, "fwd2": 4}
ROLE_X = {"gk": -50, "def": -27, "mid": 0, "fwd1": 22, "fwd2": 28}


def resolve_families(value: str) -> tuple[str, ...]:
    """Resolve a family, convenience group, comma-list, or ``all``."""
    if value == "transition":
        return ("transition_attack", "transition_defense")
    if value == "all":
        return FAMILIES
    values = tuple(part.strip().replace("-", "_") for part in value.split(","))
    unknown = sorted(set(values) - set(FAMILIES))
    if unknown:
        raise ValueError(f"Unknown scenario family: {', '.join(unknown)}")
    return values


def generate_corpus(role: str, scenario_set: str, count: int, seed: int) -> list[dict]:
    role = role.lower()
    if role not in ROLE_IDS:
        raise ValueError(f"Unknown role {role!r}")
    if count < 1:
        raise ValueError("count must be positive")
    families = resolve_families(scenario_set)
    rng = random.Random(seed)
    rows = []
    for index in range(count):
        family = families[index % len(families)]
        payload, facts = _state(rng, role, family, index)
        digest = hashlib.sha256(f"{seed}:{role}:{scenario_set}:{index}".encode()).hexdigest()[:12]
        metadata = {"scenario_id": f"scn-{digest}", "scenario_family": family, "seed": seed,
                    "role": role, "controlled_player_id": ROLE_IDS[role], **facts}
        rows.append({"metadata": metadata, "payload": payload})
    return rows


def _state(rng: random.Random, role: str, family: str, index: int):
    controlled = ROLE_IDS[role]
    own_has_ball = family in {"possession", "transition_attack", "under_pressure", "shooting_opportunity"}
    free = family == "loose_ball"
    possession_team = "none" if free else "home" if own_has_ball else "away"
    base_x = rng.uniform(28, 45) if family == "shooting_opportunity" else ROLE_X[role] + rng.uniform(-10, 10)
    ball_x, ball_y = round(max(-54, min(54, base_x)), 3), round(rng.uniform(-29, 29), 3)
    players = []
    for team in ("home", "away"):
        sign = 1 if team == "home" else -1
        for player_id in range(5):
            x = sign * ROLE_X[{0: "gk", 1: "def", 2: "mid", 3: "fwd1", 4: "fwd2"}[player_id]]
            x += rng.uniform(-7, 7)
            y = rng.uniform(-30, 30)
            if team == "home" and player_id == controlled and (own_has_ball or free):
                x, y = ball_x, ball_y
            if family == "under_pressure" and team == "away" and player_id == 1:
                x, y = ball_x + rng.uniform(1, 4), ball_y + rng.uniform(-3, 3)
            players.append({"agentId": f"agentId_{player_id}", "teamCode": team,
                            "position": {"x": round(max(-55, min(55, x)), 3),
                                         "y": round(max(-35, min(35, y)), 3)},
                            "velocity": {"x": round(rng.uniform(-2, 2), 3), "y": round(rng.uniform(-2, 2), 3)},
                            "orientation": round(rng.uniform(-180, 180), 2),
                            "stamina": round(rng.uniform(.45, 1), 3), "currentAction": 0,
                            "lastAction": "SyntheticIndependentState", "speed": round(rng.uniform(0, 2), 3),
                            "isSprinting": rng.random() < .25})
    elapsed = rng.uniform(0, 600)
    home, away = rng.randrange(5), rng.randrange(5)
    pressure = "high" if family == "under_pressure" else rng.choice(("low", "medium", "high"))
    zone = "defensive" if ball_x < -18 else "attacking" if ball_x > 18 else "middle"
    payload = {"name": f"generated-{index:06d}", "teamId": 0, "myPlayers": [controlled],
               "gameState": {"tick": rng.randrange(1, 10000), "gameTime": round(elapsed, 3),
               "playMode": "OPEN_PLAY", "modeTeamId": None, "score": {"home": home, "away": away},
               "ball": {"position": {"x": ball_x, "y": ball_y, "z": 0},
                        "velocity": {"x": round(rng.uniform(-4, 4), 3), "y": round(rng.uniform(-4, 4), 3), "z": 0},
                        "isFree": free,
                        "possessionAgentId": None if free else f"agentId_{controlled if own_has_ball else rng.randrange(5)}",
                        "rotation": {}, "angularVelocity": {}}, "players": players, "teamChat": []}}
    remaining = 600 - elapsed
    facts = {"possession_team": possession_team, "ball_zone": zone,
             "score_state": "level" if home == away else "ahead" if home > away else "behind",
             "time_remaining_bucket": "late" if remaining < 150 else "middle" if remaining < 400 else "early",
             "pressure_level": pressure}
    return payload, facts


def write_corpus(rows: list[dict], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
                    encoding="utf-8")


def load_corpus(path: str | Path) -> list[dict]:
    from runner import ScenarioError, _validate_scenario_or_raise
    rows = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ScenarioError(f"Could not load corpus {path}: {error}") from error
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("metadata"), dict) or not isinstance(row.get("payload"), dict):
                raise ValueError("expected metadata and payload objects")
            required = {"scenario_id", "scenario_family", "seed", "role", "controlled_player_id",
                        "possession_team", "ball_zone", "score_state", "time_remaining_bucket", "pressure_level"}
            missing = required - row["metadata"].keys()
            if missing:
                raise ValueError(f"missing metadata: {', '.join(sorted(missing))}")
            _validate_scenario_or_raise(row["payload"])
            rows.append(row)
        except (json.JSONDecodeError, ValueError, ScenarioError) as error:
            raise ScenarioError(f"Invalid corpus line {number}: {error}") from error
    if not rows:
        raise ScenarioError("Scenario corpus is empty")
    return rows
