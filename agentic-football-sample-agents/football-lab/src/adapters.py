"""Thin local adapter around the balanced team's public module globals."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROLE_DIRS = {"gk": "ai-gk", "def": "ai-def", "mid": "ai-mid", "fwd1": "ai-fwd1", "fwd2": "ai-fwd2"}
ROLE_LABELS = {key: key.upper() for key in ROLE_DIRS}
TEAMS = {"balanced": "ai-team-strands-balanced"}


@dataclass
class AgentCall:
    raw_output: str
    commands: list[dict]
    model_latency_ms: float
    parsing_latency_ms: float
    decision_latency_ms: float
    raw_strict_json: bool
    raw_expected_structure: bool
    tolerant_recovery: bool
    normalization: dict[str, bool]


def _stub_agentcore() -> None:
    """Provide only the decorator surface needed while importing stock main.py."""
    if "bedrock_agentcore.runtime" in sys.modules:
        return

    class LocalApp:
        class logger:
            info = warn = error = staticmethod(lambda _message: None)

        def entrypoint(self, function):
            return function

        def run(self):  # pragma: no cover - main guard is not entered on import
            raise RuntimeError("AgentCore runtime is unavailable in the local adapter")

    package = types.ModuleType("bedrock_agentcore")
    runtime = types.ModuleType("bedrock_agentcore.runtime")
    runtime.BedrockAgentCoreApp = LocalApp
    sys.modules["bedrock_agentcore"] = package
    sys.modules["bedrock_agentcore.runtime"] = runtime


def load_agent(team: str, role: str, root: Path | None = None):
    """Import and return one unmodified stock agent module."""
    team = team.lower()
    role = role.lower()
    if team not in TEAMS:
        raise ValueError(f"Unknown team {team!r}; available teams: {', '.join(TEAMS)}")
    if role not in ROLE_DIRS:
        raise ValueError(f"Unknown agent {role!r}; available agents: {', '.join(ROLE_DIRS)}")
    agents_root = root or Path(__file__).resolve().parents[2]
    shared = agents_root / "lib"
    module_path = agents_root / TEAMS[team] / ROLE_DIRS[role] / "src" / "main.py"
    sys.path.insert(0, str(shared)) if str(shared) not in sys.path else None
    _stub_agentcore()
    name = f"football_lab_stock_{team}_{role}"
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load stock agent from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke_stock_agent(module, payload: dict, clock: Callable[[], float]) -> AgentCall:
    """Run the stock model, summarizer and parser without AgentCore transport."""
    from json_tolerant import parse_json_tolerant
    from parsing import VALID_COMMANDS, parse_commands
    from state import summarize_state

    game_state = payload["gameState"]
    team_id = payload.get("teamId", 0)
    # The selected stock role, not scenario ordering, determines the controlled player.
    player_id = module.MY_PLAYER_ID
    decision_start = clock()
    prompt = summarize_state(game_state, team_id, player_id, module.POSITION_LABEL)
    model_start = clock()
    response = module.agent(prompt)
    model_end = clock()
    model_latency_ms = (model_end - model_start) * 1000
    raw = str(response)

    try:
        strict_value = json.loads(raw)
        raw_strict_json = True
    except (json.JSONDecodeError, TypeError):
        strict_value = None
        raw_strict_json = False
    # Observe the shared tolerant decoder before calling the stock parser. This does not
    # replace parsing: parse_commands remains the only source of returned commands.
    observed = strict_value
    if observed is None:
        tolerant_value = parse_json_tolerant(raw)
        if tolerant_value is not None:
            observed = tolerant_value[0]
    raw_expected_structure = isinstance(observed, list) or (
        isinstance(observed, dict) and "commandType" in observed
    )

    parse_start = clock()
    recovered = []
    commands = parse_commands(raw, team_id, player_id, lambda value: recovered.append(value))
    parse_end = clock()
    before = observed if isinstance(observed, list) else [observed] if isinstance(observed, dict) else []
    normalization = _normalization(before, commands, team_id, player_id, VALID_COMMANDS)
    return AgentCall(
        raw_output=raw,
        commands=commands,
        model_latency_ms=model_latency_ms,
        parsing_latency_ms=(parse_end - parse_start) * 1000,
        decision_latency_ms=(parse_end - decision_start) * 1000,
        raw_strict_json=raw_strict_json,
        raw_expected_structure=raw_expected_structure,
        tolerant_recovery=bool(recovered),
        normalization=normalization,
    )


def _normalization(before, after, team_id, player_id, valid_commands) -> dict[str, bool]:
    """Describe observable stock-parser changes without changing parser behavior."""
    source = [item for item in before if isinstance(item, dict)]
    by_type = {command.get("commandType"): command for command in after}
    target_types = {"PASS", "MARK", "FOLLOW_PLAYER", "GK_DISTRIBUTE", "SLIDE_TACKLE"}
    return {
        "player_id_overwritten": any("playerId" in cmd and cmd["playerId"] != player_id for cmd in source),
        "team_id_added_or_overwritten": any(cmd.get("teamId") != team_id for cmd in source),
        "missing_target_player_id_supplied": any(
            cmd.get("commandType") in target_types
            and isinstance(cmd.get("parameters"), dict)
            and cmd.get("parameters", {}).get("target_player_id") is None
            and by_type.get(cmd.get("commandType"), {}).get("parameters", {}).get("target_player_id") is not None
            for cmd in source
        ),
        "move_coordinates_clamped": any(
            cmd.get("commandType") == "MOVE_TO"
            and cmd.get("parameters", {}).get(axis)
            != by_type.get("MOVE_TO", {}).get("parameters", {}).get(axis)
            for cmd in source for axis in ("target_x", "target_y")
        ),
        "unknown_commands_filtered": any(cmd.get("commandType") not in valid_commands for cmd in source),
    }
