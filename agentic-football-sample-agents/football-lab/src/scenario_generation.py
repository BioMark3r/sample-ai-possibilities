"""Deterministic, independent synthetic decision-state generation.

Family geometry is intentionally constrained rather than simulated; every row is one decision.
Home is the controlled team and attacks toward +x. Player IDs are team-relative 0-4, matching the
repository's current-schema fixture; the lab adapter disambiguates the possessing side by geometry.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

FAMILIES = ("possession", "transition_attack", "transition_defense", "under_pressure",
            "shooting_opportunity", "loose_ball", "defensive_shape")
ROLE_IDS = {"gk": 0, "def": 1, "mid": 2, "fwd1": 3, "fwd2": 4}
ROLE_X = (-50, -27, 0, 22, 28)
MATCH_DURATION_SECONDS = 300.0
EARLY_END_SECONDS = 100.0
LATE_START_SECONDS = 225.0
NORMAL_PLAY_MODE = "PlayOn"
FIELD_X = (-55.0, 55.0)
FIELD_Y = (-35.0, 35.0)


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


def _player(player_id, team, x, y, rng, *, velocity_x=None):
    """Build a current-schema player with the runtime's team-relative role ID."""
    return {"agentId": f"agentId_{player_id}", "teamCode": team,
            "position": {"x": round(max(FIELD_X[0], min(FIELD_X[1], x)), 3),
                         "y": round(max(FIELD_Y[0], min(FIELD_Y[1], y)), 3)},
            "velocity": {"x": round(rng.uniform(-1.5, 1.5) if velocity_x is None else velocity_x, 3),
                         "y": round(rng.uniform(-1.5, 1.5), 3)},
            "orientation": round(rng.uniform(-180, 180), 2), "stamina": round(rng.uniform(.55, 1), 3),
            "currentAction": 0, "lastAction": "SyntheticIndependentState",
            "speed": round(rng.uniform(0, 2), 3), "isSprinting": rng.random() < .25}


def _base_players(rng):
    players = []
    for team in ("home", "away"):
        sign = 1 if team == "home" else -1
        for player_id, role_x in enumerate(ROLE_X):
            players.append(_player(player_id, team, sign * role_x + rng.uniform(-3, 3),
                                   rng.uniform(-27, 27), rng))
    return players


def _set_position(players, team, player_id, x, y):
    player = next(item for item in players
                  if item["teamCode"] == team and item["agentId"] == f"agentId_{player_id}")
    player["position"] = {"x": round(x, 3), "y": round(y, 3)}
    return player


def _elapsed_time(rng, index):
    """Stratification makes every match-time bucket reachable in corpora of 3+ rows."""
    bucket = index % 3
    if bucket == 0:
        return rng.uniform(0, EARLY_END_SECONDS)
    if bucket == 1:
        return rng.uniform(EARLY_END_SECONDS, LATE_START_SECONDS)
    return rng.uniform(LATE_START_SECONDS, MATCH_DURATION_SECONDS)


def _state(rng: random.Random, role: str, family: str, index: int):
    controlled = ROLE_IDS[role]
    players = _base_players(rng)
    free = family == "loose_ball"
    possession_team = "none" if free else "away" if family in {"transition_defense", "defensive_shape"} else "home"
    carrier_team, carrier_id = possession_team, controlled
    ball_velocity_x = rng.uniform(-.5, .5)

    if family == "possession":
        # Settled home possession, compact support, and moderate (6-10m) pressure.
        carrier_id = controlled if rng.random() < .5 else (controlled + 1) % 5
        bx, by = rng.uniform(-12, 12), rng.uniform(-16, 16)
        _set_position(players, "home", carrier_id, bx, by)
        _set_position(players, "home", controlled, bx - 4, by + 4) if carrier_id != controlled else None
        _set_position(players, "away", 1, bx + 8, by + 1)
        for pid in (2, 3, 4):
            _set_position(players, "away", pid, bx + 12 + 4 * (pid - 2), -18 + 12 * (pid - 2))
    elif family == "transition_attack":
        # Home advances into open +x space with support ahead; most opponents trail the ball.
        bx, by = rng.uniform(-8, 10), rng.uniform(-14, 14)
        _set_position(players, "home", controlled, bx, by)
        _set_position(players, "home", 3 if controlled != 3 else 4, bx + rng.uniform(12, 20), by - 8)
        _set_position(players, "home", 4 if controlled != 4 else 2, bx + rng.uniform(16, 25), by + 9)
        for pid in (1, 2, 3):
            _set_position(players, "away", pid, bx - rng.uniform(3, 16), rng.uniform(-25, 25))
        _set_position(players, "away", 4, bx + 25, rng.uniform(-20, 20))
        ball_velocity_x = rng.uniform(1.5, 4)
    elif family == "transition_defense":
        # Away advances toward -x; the controlled team is goal-side incomplete and recovering.
        carrier_id = rng.choice((1, 2, 3, 4))
        bx, by = rng.uniform(-18, 2), rng.uniform(-16, 16)
        _set_position(players, "away", carrier_id, bx, by)
        _set_position(players, "away", (carrier_id + 1) % 5 or 1, bx - rng.uniform(8, 16), by + 8)
        _set_position(players, "home", controlled, bx + rng.uniform(8, 16), by + rng.uniform(-6, 6))
        for pid in (2, 3, 4):
            if pid != controlled:
                _set_position(players, "home", pid, bx + rng.uniform(10, 25), rng.uniform(-25, 25))
        ball_velocity_x = rng.uniform(-4, -1.5)
    elif family == "under_pressure":
        # Controlled player holds the ball, an opponent is within 2-4m, and two outlets remain.
        bx, by = rng.uniform(-8, 16), rng.uniform(-15, 15)
        _set_position(players, "home", controlled, bx, by)
        _set_position(players, "away", 1, bx + rng.uniform(2, 3.5), by + rng.uniform(-1.5, 1.5))
        for offset, pid in zip((-1, 1), [p for p in (1, 3, 4) if p != controlled][:2]):
            _set_position(players, "home", pid, bx + rng.uniform(8, 14), by + offset * rng.uniform(8, 14))
    elif family == "shooting_opportunity":
        # Controlled possession 13-27m from the +x goal, central angle, with GK and defender context.
        bx, by = rng.uniform(30, 42), rng.uniform(-12, 12)
        _set_position(players, "home", controlled, bx, by)
        _set_position(players, "away", 0, 51, rng.uniform(-3, 3))
        _set_position(players, "away", 1, bx + rng.uniform(5, 10), by + rng.choice((-1, 1)) * rng.uniform(4, 8))
    elif family == "loose_ball":
        # Free/rebounding ball contested within 2-5m by the controlled player and an opponent.
        carrier_team, carrier_id = None, None
        bx, by = rng.uniform(-15, 15), rng.uniform(-18, 18)
        _set_position(players, "home", controlled, bx - rng.uniform(2, 4), by + rng.uniform(-1, 1))
        _set_position(players, "away", 2, bx + rng.uniform(2, 4), by + rng.uniform(-1, 1))
        ball_velocity_x = rng.uniform(-3, 3)
    else:  # defensive_shape
        # Settled away possession against four organized home outfield lines behind the ball.
        carrier_id = 2
        bx, by = rng.uniform(2, 14), rng.uniform(-10, 10)
        _set_position(players, "away", carrier_id, bx, by)
        for pid, x, y in ((1, -31, -12), (2, -24, 0), (3, -17, 12), (4, -12, -15)):
            _set_position(players, "home", pid, x + rng.uniform(-2, 2), y + rng.uniform(-2, 2))

    elapsed = _elapsed_time(rng, index)
    home, away = rng.randrange(5), rng.randrange(5)
    ball_zone = "defensive" if bx < -18 else "attacking" if bx > 18 else "middle"
    possession_agent_id = None if free else f"agentId_{carrier_id}"
    payload = {"name": f"generated-{index:06d}", "teamId": 0, "myPlayers": [controlled],
               "gameState": {"tick": rng.randrange(1, 10000), "gameTime": round(elapsed, 3),
               "playMode": NORMAL_PLAY_MODE, "modeTeamId": None, "score": {"home": home, "away": away},
               "ball": {"position": {"x": round(bx, 3), "y": round(by, 3), "z": 0},
                        "velocity": {"x": round(ball_velocity_x, 3), "y": round(rng.uniform(-2, 2), 3), "z": 0},
                        "isFree": free, "possessionAgentId": possession_agent_id,
                        "rotation": {}, "angularVelocity": {}}, "players": players, "teamChat": []}}
    remaining = MATCH_DURATION_SECONDS - elapsed
    facts = {"possession_team": possession_team, "ball_zone": ball_zone,
             "score_state": "level" if home == away else "ahead" if home > away else "behind",
             "time_remaining_bucket": "early" if elapsed < EARLY_END_SECONDS else
                                      "late" if elapsed >= LATE_START_SECONDS else "middle",
             "pressure_level": "high" if family == "under_pressure" else
                               "medium" if family in {"possession", "defensive_shape"} else "low"}
    assert 0 <= remaining <= MATCH_DURATION_SECONDS
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
