"""Offline Week 2 observation, geometry, regression, and reporting tools."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

try:
    from .validation import validate_scenario
    from .validation import COMMAND_PARAMETERS
except ImportError:  # Flat src/ imports used by the command-line tools.
    from validation import validate_scenario
    from validation import COMMAND_PARAMETERS

ROLES = ("gk", "def", "mid", "fwd1", "fwd2")
SEVERITIES = ("low", "medium", "high", "critical")
SEVERITY_ORDER = {value: index for index, value in enumerate(SEVERITIES)}
TAXONOMY = {
    "attack": ("missed_shooting_opportunity", "poor_shot_selection", "unnecessary_backward_pass",
               "missed_forward_pass", "possession_loss", "poor_off_ball_movement", "slow_transition_attack"),
    "defense": ("over_pressing", "under_pressing", "lost_defensive_shape", "missed_intercept",
                "poor_marking", "failed_transition_defense"),
    "goalkeeper": ("poor_distribution", "unsafe_distribution", "positioning_issue"),
    "general": ("invalid_command", "model_exception", "timeout", "throttled", "repeated_action", "unknown",
                "authentication", "access_denied", "dependency_failure"),
}
INFRASTRUCTURE_PROBLEMS = frozenset(("timeout", "throttled", "authentication", "access_denied",
                                     "dependency_failure", "model_exception"))
INFRASTRUCTURE_STATUS = {"timeout": "timeout", "throttled": "throttled", "authentication": "auth_error",
                         "access_denied": "access_denied", "dependency_failure": "dependency_error",
                         "model_exception": "unknown_error"}
ROLE_PLAYER_IDS = {"gk": 0, "def": 1, "mid": 2, "fwd1": 3, "fwd2": 4}
SUGGESTIONS = {
    "missed_shooting_opportunity": "When you have possession in the attacking zone and are within a reasonable shooting distance with a viable path to goal, prefer SHOOT over a backward or lateral PASS unless immediate pressure makes the shot clearly unavailable. Apply this shoot-vs-pass behavior consistently.",
    "over_pressing": "Do not abandon defensive shape solely to pressure the ball. PRESS_BALL only when the ball carrier can be challenged without exposing a large gap behind you.",
    "unnecessary_backward_pass": "During an advancing transition, prefer a safe forward PASS or forward movement when available rather than recycling possession backward by default.",
    "poor_shot_selection": "Use SHOOT only when you have a viable path to goal from a reasonable shooting distance; otherwise retain possession or make a safe PASS.",
    "poor_distribution": "Distribute to a safely available teammate rather than forcing the ball into immediate pressure.",
}


def infer_controlled_player_id(payload, role=None, explicit=None):
    """Apply the documented identity precedence without guessing from arbitrary state."""
    if explicit is not None:
        return explicit
    players = payload.get("myPlayers") if isinstance(payload, dict) else None
    if isinstance(players, list) and len(players) == 1:
        return players[0]
    return ROLE_PLAYER_IDS.get(role.lower()) if isinstance(role, str) else None


def normalize_action(value):
    """Return a known command type from a string or common command envelope."""
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
        try:
            decoded = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            decoded = None
        if decoded is not None:
            return normalize_action(decoded)
        candidate = candidate.upper()
        return candidate if candidate in COMMAND_PARAMETERS else None
    if isinstance(value, list):
        return normalize_action(value[0]) if value else None
    if isinstance(value, dict):
        for key in ("commandType", "action_type", "actionType", "action", "command", "parsed_command"):
            if key in value:
                found = normalize_action(value[key])
                if found:
                    return found
    return None


def _telemetry_value(value, *keys):
    """Find the first named field in a small, variably wrapped telemetry record."""
    if not isinstance(value, dict):
        return None
    for key in keys:
        if key in value and value[key] is not None:
            return value[key]
    for wrapper in ("request", "response", "payload", "body", "input", "metadata", "telemetry", "event"):
        found = _telemetry_value(value.get(wrapper), *keys)
        if found is not None:
            return found
    return None


def _telemetry_payload(record):
    """Locate a complete payload while retaining the selected object byte-for-byte logically."""
    candidates = [record] if "gameState" in record else []
    for wrapper in ("request", "payload", "body", "input"):
        value = record.get(wrapper)
        if isinstance(value, dict):
            candidates.append(value)
            for inner in ("payload", "body", "input"):
                if isinstance(value.get(inner), dict): candidates.append(value[inner])
    full = next((value for value in candidates if not validate_scenario(value)), None)
    if full is not None:
        return deepcopy(full)
    # An explicitly named payload/game-state envelope is still valuable as a
    # partial observation.  Do not synthesize absent fields to make it valid.
    return deepcopy(candidates[0]) if candidates else None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stable_id(prefix, value):
    return f"{prefix}-{hashlib.sha256(_canonical(value).encode()).hexdigest()[:16]}"


def taxonomy_values():
    return {item for values in TAXONOMY.values() for item in values}


class Week2Store:
    def __init__(self, root="week2"):
        self.root = Path(root)
        for name in ("matches", "observations", "regressions", "reports"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def _read(self, kind, identity):
        path = self.root / kind / f"{identity}.json"
        if not path.exists():
            raise ValueError(f"unknown {kind[:-1]}: {identity}")
        return json.loads(path.read_text(encoding="utf-8"))

    def new_match(self, match_id, **metadata):
        if not match_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in match_id):
            raise ValueError("match ID may contain only letters, digits, '-' and '_'")
        document = {"match_id": match_id, **{k: v for k, v in metadata.items() if v is not None}}
        path = self.root / "matches" / f"{match_id}.json"
        if path.exists() and json.loads(path.read_text()) != document:
            raise ValueError(f"match already exists with different metadata: {match_id}")
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return document

    def observations(self, match_id=None, **filters):
        rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((self.root / "observations").glob("*.json"))]
        rows = [r for r in rows if match_id is None or r["match_id"] == match_id]
        locations = {"family": ("scenario_mapping", "suggested_scenario_family"),
                     "possession": ("analysis", "possession_side"), "ball_zone": ("analysis", "ball_zone"),
                     "score_state": ("analysis", "score_state"), "pressure": ("analysis", "pressure_estimate"),
                     "match_time_bucket": ("analysis", "match_time_bucket")}
        for name, expected in filters.items():
            if expected is None: continue
            if name == "action":
                rows = [r for r in rows if r.get("observed_action") == expected.upper()]
            elif name in locations:
                outer, inner = locations[name]
                rows = [r for r in rows if r.get(outer, {}).get(inner) == expected]
            else:
                rows = [r for r in rows if r.get(name) == expected]
        return rows

    def observe(self, match_id, role=None, problem_type="unknown", severity="medium", payload=None, **fields):
        self._read("matches", match_id)
        role = role.lower() if role else None
        if role and role not in ROLES:
            raise ValueError(f"role must be one of: {', '.join(ROLES)}")
        if problem_type not in taxonomy_values():
            raise ValueError(f"unknown problem type: {problem_type}")
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of: {', '.join(SEVERITIES)}")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        controlled_player_id = infer_controlled_player_id(payload, role, fields.get("controlled_player_id"))
        if "observed_action" in fields and fields["observed_action"] is not None:
            action = normalize_action(fields["observed_action"])
            if not action:
                raise ValueError("observed action must be a known command type")
            fields["observed_action"] = action
        document = {"match_id": match_id, "problem_type": problem_type, "severity": severity}
        document["infrastructure_status"] = INFRASTRUCTURE_STATUS.get(problem_type, "ok")
        if role: document["role"] = role
        if payload is not None: document["payload"] = deepcopy(payload)
        if controlled_player_id is not None: fields["controlled_player_id"] = controlled_player_id
        document.update({k: v for k, v in fields.items() if v is not None and v != []})
        if not payload and not document.get("notes"):
            raise ValueError("a partial observation requires notes; otherwise provide a payload")
        document["observation_type"] = "full_state" if payload and not validate_scenario(payload) else "partial"
        if payload and document["observation_type"] == "partial":
            document["payload_validation_errors"] = validate_scenario(payload)
        identity_source = deepcopy(document)
        document["observation_id"] = _stable_id("obs", identity_source)
        if document["observation_type"] == "full_state" and controlled_player_id is not None:
            document["analysis"] = analyze_state(payload, role, controlled_player_id)
            document["scenario_mapping"] = map_scenario_family(document["analysis"])
        elif document["observation_type"] == "full_state":
            document["scenario_mapping"] = {"suggested_scenario_family": "unknown",
                                            "reasons": ["controlled player could not be inferred"]}
        path = self.root / "observations" / f'{document["observation_id"]}.json'
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return document

    def annotate(self, observation_id, problem_type, severity=None, notes=None):
        row = self._read("observations", observation_id)
        if problem_type not in taxonomy_values(): raise ValueError(f"unknown problem type: {problem_type}")
        if severity is not None and severity not in SEVERITIES: raise ValueError(f"severity must be one of: {', '.join(SEVERITIES)}")
        row["problem_type"] = problem_type
        row["infrastructure_status"] = INFRASTRUCTURE_STATUS.get(problem_type, "ok")
        if severity is not None: row["severity"] = severity
        if notes is not None: row["notes"] = notes
        (self.root / "observations" / f"{observation_id}.json").write_text(
            json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return row

    def import_telemetry(self, match_id, input_path):
        counts = {"records_read": 0, "full_state_observations": 0,
                  "partial_observations": 0, "ignored_unrecognized": 0}
        with Path(input_path).open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip(): continue
                counts["records_read"] += 1
                try: record = json.loads(line)
                except json.JSONDecodeError:
                    counts["ignored_unrecognized"] += 1; continue
                if not isinstance(record, dict):
                    counts["ignored_unrecognized"] += 1; continue
                payload = _telemetry_payload(record)
                role = _telemetry_value(record, "role", "playerRole", "player_role")
                role = role.lower() if isinstance(role, str) and role.lower() in ROLES else None
                player_id = _telemetry_value(record, "controlled_player_id", "playerId", "player_id")
                if isinstance(player_id, str) and player_id.isdigit(): player_id = int(player_id)
                action = normalize_action(_telemetry_value(record, "parsed_command", "parsedCommand", "action", "command", "model_response", "modelResponse"))
                status = _telemetry_value(record, "exception", "infrastructure_status", "status")
                useful = payload is not None or role is not None or player_id is not None or action is not None or status is not None
                if not useful:
                    counts["ignored_unrecognized"] += 1; continue
                if role is None and isinstance(player_id, int):
                    role = next((r for r, pid in ROLE_PLAYER_IDS.items() if pid == player_id), None)
                fields = {"controlled_player_id": player_id, "observed_action": action,
                          "telemetry_record": deepcopy(record)}
                if payload is None:
                    fields["notes"] = f"Imported telemetry record {line_number}" + (f": {status}" if status is not None else "")
                try:
                    row = self.observe(match_id, role, "unknown", "medium", payload, **fields)
                except ValueError:
                    counts["ignored_unrecognized"] += 1; continue
                key = "full_state_observations" if row["observation_type"] == "full_state" else "partial_observations"
                counts[key] += 1
        return counts

    def promote(self, observation_id):
        observation = self._read("observations", observation_id)
        if observation["problem_type"] in INFRASTRUCTURE_PROBLEMS:
            raise ValueError("infrastructure observations cannot become tactical regressions")
        payload = observation.get("payload")
        errors = validate_scenario(payload)
        if observation.get("observation_type") != "full_state" or errors:
            raise ValueError("only observations with a valid full game state can be promoted: " + "; ".join(errors))
        regression_id = _stable_id("reg", {"observation_id": observation_id, "payload": payload})
        annotations = {k: deepcopy(v) for k, v in observation.items()
                       if k not in {"payload", "analysis", "scenario_mapping"}}
        row = {"metadata": {"scenario_id": regression_id, "source": "week2_official_match",
                            "scenario_family": observation["scenario_mapping"]["suggested_scenario_family"],
                            "role": observation.get("role"), "observation_id": observation_id,
                            "controlled_player_id": observation.get("controlled_player_id"),
                            "match_id": observation["match_id"], "annotations": annotations},
               "payload": deepcopy(payload)}
        path = self.root / "regressions" / f"{regression_id}.json"
        path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return row


def _team(player):
    return player.get("teamCode") or ("home" if player.get("teamId") == 0 else "away")


def _position(value):
    pos = value.get("position", value) if isinstance(value, dict) else {}
    return (float(pos.get("x", 0)), float(pos.get("y", 0)))


def _distance(a, b):
    return round(math.dist(_position(a), _position(b)), 2)


def analyze_state(payload, role=None, controlled_player_id=None):
    errors = validate_scenario(payload)
    if errors: raise ValueError("invalid payload: " + "; ".join(errors))
    state, team_id = payload["gameState"], payload.get("teamId", 0)
    side = "home" if team_id == 0 else "away"
    opponents_side = "away" if side == "home" else "home"
    controlled_player_id = controlled_player_id if controlled_player_id is not None else (payload.get("myPlayers") or [None])[0]
    players = state["players"]
    controlled = next((p for p in players if _team(p) == side and
                       str(p.get("agentId", p.get("playerId", ""))).split("_")[-1] == str(controlled_player_id)), None)
    if controlled is None: raise ValueError("controlled player is not present in gameState.players")
    ball = state["ball"]; ball_pos = _position(ball); controlled_pos = _position(controlled)
    holder_id = ball.get("possessionAgentId")
    candidates = [p for p in players if str(p.get("agentId", p.get("playerId"))) == str(holder_id)]
    holder = min(candidates, key=lambda p: _distance(p, ball), default=None)
    possession = "loose" if ball.get("isFree") or not holder_id else (_team(holder) if holder else "unknown")
    teammates = [p for p in players if _team(p) == side and p is not controlled]
    opponents = [p for p in players if _team(p) == opponents_side]
    direction = 1 if side == "home" else -1
    nearest_opp = min(opponents, key=lambda p: _distance(controlled, p), default=None)
    mate_distances = sorted(({"player_id": p.get("agentId", p.get("playerId")), "distance": _distance(controlled, p)} for p in teammates), key=lambda x: x["distance"])
    opp_distance = _distance(controlled, nearest_opp) if nearest_opp else None
    x, y = ball_pos; attack_goal, own_goal = (52.5, 0), (-52.5, 0)
    if direction < 0: attack_goal, own_goal = own_goal, attack_goal
    score = state.get("score", {})
    ours, theirs = (score.get("home"), score.get("away")) if side == "home" else (score.get("away"), score.get("home"))
    score_state = "unknown" if ours is None or theirs is None else ("level" if ours == theirs else "ahead" if ours > theirs else "behind")
    game_time = state.get("gameTime")
    time_bucket = "unknown" if game_time is None else "early" if game_time < 100 else "middle" if game_time < 200 else "late"
    ahead = lambda p: direction * (_position(p)[0] - x) > 0
    return {"role": role, "possession_side": possession,
            "controlled_player_possession": holder is controlled, "ball_position": {"x": x, "y": y},
            "ball_zone": "attacking" if direction*x > 17.5 else "defensive" if direction*x < -17.5 else "middle",
            "score_state": score_state, "match_time_bucket": time_bucket,
            "nearest_opponent": None if not nearest_opp else {"player_id": nearest_opp.get("agentId", nearest_opp.get("playerId")), "distance": opp_distance},
            "nearest_teammates": mate_distances[:3],
            "pressure_estimate": "high" if opp_distance is not None and opp_distance < 5 else "medium" if opp_distance is not None and opp_distance < 12 else "low",
            "distance_to_attacking_goal": _distance(ball, {"x": attack_goal[0], "y": 0}),
            "distance_to_own_goal": _distance(ball, {"x": own_goal[0], "y": 0}),
            "controlled_player_goal_side_of_ball": direction * (controlled_pos[0] - x) <= 0,
            "teammates_ahead_of_ball": sum(ahead(p) for p in teammates),
            "opponents_ahead_of_ball": sum(ahead(p) for p in opponents),
            "opponents_behind_ball": sum(not ahead(p) for p in opponents)}


def map_scenario_family(facts):
    if facts["possession_side"] == "loose": return {"suggested_scenario_family": "loose_ball", "reasons": ["ball is loose"]}
    if facts["controlled_player_possession"] and facts["ball_zone"] == "attacking" and facts["distance_to_attacking_goal"] <= 30:
        return {"suggested_scenario_family": "shooting_opportunity", "reasons": ["controlled player has possession", "ball is in attacking zone", f'distance to goal is {facts["distance_to_attacking_goal"]}m']}
    if facts["controlled_player_possession"] and facts["pressure_estimate"] == "high":
        return {"suggested_scenario_family": "under_pressure", "reasons": ["controlled player has possession", "nearest opponent is within 5m"]}
    own = "home" if facts["possession_side"] == "home" else "away"
    if facts["possession_side"] not in ("unknown", "loose") and facts["ball_zone"] == "middle":
        family = "transition_attack" if facts["controlled_player_possession"] else "transition_defense"
        return {"suggested_scenario_family": family, "reasons": [f"{own} side has possession", "ball is in the middle zone"]}
    if facts["controlled_player_possession"]: return {"suggested_scenario_family": "possession", "reasons": ["controlled player has possession"]}
    return {"suggested_scenario_family": "defensive_shape", "reasons": ["opposition possession or defensive context"]}


def report_data(store, match_id):
    match = store._read("matches", match_id); all_rows = store.observations(match_id)
    infrastructure = [r for r in all_rows if r["problem_type"] in INFRASTRUCTURE_PROBLEMS]
    tactical = [r for r in all_rows if r not in infrastructure]
    counts = Counter((r.get("role", "unspecified"), r["problem_type"]) for r in tactical)
    repeated = [{"role": role, "problem_type": problem, "count": count} for (role, problem), count in sorted(counts.items()) if count > 1]
    suggestions = [{**item, "recommendation": SUGGESTIONS.get(item["problem_type"],
                    "Consider one narrowly scoped, role-specific instruction candidate for review.").format(role=item["role"].upper()),
                    "related_observations": [r["observation_id"] for r in tactical if r.get("role", "unspecified") == item["role"] and r["problem_type"] == item["problem_type"]]}
                   for item in repeated]
    return {"match": match, "observation_count": len(all_rows), "tactical_observations": tactical,
            "infrastructure_observations": infrastructure, "repeated_patterns": repeated,
            "experiment_suggestions": suggestions}


def markdown_report(data):
    m=data["match"]; lines=[f'# Week 2 report: {m["match_id"]}', "", "## Match summary",
        f'- Opponent: {m.get("opponent", "not recorded")}', f'- Final score: {m.get("final_score", "not recorded")}',
        f'- Configuration: {m.get("configuration", "not recorded")}', f'- Git commit: {m.get("git_sha", "not recorded")}',
        f'- Observations: {data["observation_count"]}', "", "## Highest-severity observations"]
    rows=sorted(data["tactical_observations"], key=lambda r: SEVERITY_ORDER[r["severity"]], reverse=True)
    for r in rows: lines.append(f'- **{r["severity"].upper()}** {r.get("role", "unspecified").upper()} / {r["problem_type"]} / {r.get("scenario_mapping", {}).get("suggested_scenario_family", "partial/manual")}: {r.get("notes", "no notes")}' )
    lines += ["", "## Role breakdown"]
    for role in ROLES:
        c=Counter(r["problem_type"] for r in rows if r.get("role")==role); lines.append(f'### {role.upper()}')
        lines.extend([f'- {p}: {n}' for p,n in sorted(c.items())] or ["- No observations."])
    lines += ["", "## Repeated patterns"]
    lines.extend([f'- {x["role"].upper()}: {x["problem_type"]}: {x["count"]}' for x in data["repeated_patterns"]] or ["- None recorded."])
    lines += ["", "## Suggested next experiments"]
    for x in data["experiment_suggestions"]:
        lines += [f'### {x["role"].upper()}: {x["problem_type"]}', f'Observed pattern: {x["count"]} observations.', x["recommendation"], "Related observations:", *[f'- {i}' for i in x["related_observations"]]]
    if not data["experiment_suggestions"]: lines.append("- No strongly repeated tactical pattern yet.")
    lines += ["", "## Infrastructure (not tactical regressions)"]
    lines.extend([f'- {r["problem_type"]}: {r.get("notes", "no notes")}' for r in data["infrastructure_observations"]] or ["- None recorded."])
    lines += ["", "> Descriptive observations and experiment ideas only; no causal or outcome claim is made.", ""]
    return "\n".join(lines)


def candidate_config(store, match_id, problem):
    rows=[r for r in store.observations(match_id) if r["problem_type"]==problem and r["problem_type"] not in INFRASTRUCTURE_PROBLEMS]
    if not rows: raise ValueError("no tactical observations match that problem")
    role=Counter(r.get("role") for r in rows if r.get("role")).most_common(1)
    if not role: raise ValueError("matching observations do not identify a role")
    role=role[0][0]; instruction=SUGGESTIONS.get(problem, "Review this observed behavior and add one narrow instruction for {role}.").format(role=role.upper())
    return {"name": f"{match_id}-{role}-{problem.replace('_', '-')}", "candidate": True,
            "review_required": True, "source_observations": [r["observation_id"] for r in rows],
            "global": {}, "roles": {role: {"instructions": [instruction]}}}


def trends(store):
    matches=[json.loads(p.read_text()) for p in sorted((store.root/"matches").glob("*.json"))]
    ids=[m["match_id"] for m in matches]; rows=store.observations()
    problems=sorted({r["problem_type"] for r in rows if r["problem_type"] not in INFRASTRUCTURE_PROBLEMS})
    return {"matches": ids, "problems": {p: [sum(r["match_id"]==mid and r["problem_type"]==p for r in rows) for mid in ids] for p in problems},
            "note": "Descriptive counts only; they do not establish causality."}
