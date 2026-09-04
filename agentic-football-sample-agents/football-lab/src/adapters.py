"""Thin local adapter around the balanced team's public module globals."""

from __future__ import annotations

import importlib.util
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
    malformed_model_output: bool


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
    from parsing import parse_commands
    from state import summarize_state

    game_state = payload["gameState"]
    team_id = payload.get("teamId", 0)
    players = payload.get("myPlayers", [module.MY_PLAYER_ID])
    player_id = players[0] if players else module.MY_PLAYER_ID
    prompt = summarize_state(game_state, team_id, player_id, module.POSITION_LABEL)
    start = clock()
    response = module.agent(prompt)
    model_latency_ms = (clock() - start) * 1000
    raw = str(response)
    recovered = []
    commands = parse_commands(raw, team_id, player_id, lambda value: recovered.append(value))
    return AgentCall(raw, commands, model_latency_ms, not commands or bool(recovered))
