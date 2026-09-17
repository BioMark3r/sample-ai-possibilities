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
except ImportError:  # Flat src/ imports used by the command-line tools.
    from validation import validate_scenario

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
SUGGESTIONS = {
    "missed_shooting_opportunity": "Consider a narrow tactical candidate clarifying shoot-vs-pass behavior in the attacking zone for {role}.",
    "over_pressing": "Consider a narrow tactical candidate clarifying press conditions and shape preservation for {role}.",
    "unnecessary_backward_pass": "Consider a narrow tactical candidate clarifying forward-pass bias during transitions for {role}.",
    "poor_shot_selection": "Consider a narrow tactical candidate clarifying shot-selection conditions for {role}.",
    "poor_distribution": "Consider a narrow tactical candidate clarifying safe distribution priorities for {role}.",
}


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

    def observations(self, match_id=None):
        rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((self.root / "observations").glob("*.json"))]
        return [r for r in rows if match_id is None or r["match_id"] == match_id]

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
        document = {"match_id": match_id, "problem_type": problem_type, "severity": severity}
        document["infrastructure_status"] = INFRASTRUCTURE_STATUS.get(problem_type, "ok")
        if role: document["role"] = role
        if payload is not None: document["payload"] = deepcopy(payload)
        document.update({k: v for k, v in fields.items() if v is not None and v != []})
        if not payload and not document.get("notes"):
            raise ValueError("a partial observation requires notes; otherwise provide a payload")
        document["observation_type"] = "full_state" if payload and not validate_scenario(payload) else "partial"
        if payload and document["observation_type"] == "partial":
            document["payload_validation_errors"] = validate_scenario(payload)
        identity_source = deepcopy(document)
        document["observation_id"] = _stable_id("obs", identity_source)
        if document["observation_type"] == "full_state":
            document["analysis"] = analyze_state(payload, role, fields.get("controlled_player_id"))
            document["scenario_mapping"] = map_scenario_family(document["analysis"])
        path = self.root / "observations" / f'{document["observation_id"]}.json'
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return document

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
