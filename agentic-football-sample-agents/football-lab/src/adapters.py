"""Thin local adapter around stock teams' public module globals."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import signal
import sys
import threading
import types
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROLE_DIRS = {"gk": "ai-gk", "def": "ai-def", "mid": "ai-mid", "fwd1": "ai-fwd1", "fwd2": "ai-fwd2"}
ROLE_LABELS = {key: key.upper() for key in ROLE_DIRS}
TEAMS = {
    "balanced": "ai-team-strands-balanced",
    "extremely-aggressive": "ai-team-strands-extremely-aggressive",
    "extremely-defensive": "ai-team-strands-extremely-defensive",
}
MODEL_IDS = {"gk": "us.amazon.nova-micro-v1:0", "def": "us.amazon.nova-lite-v1:0",
             "mid": "us.amazon.nova-pro-v1:0", "fwd1": "us.amazon.nova-micro-v1:0",
             "fwd2": "us.amazon.nova-lite-v1:0"}

DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_READ_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 1
DEFAULT_MODEL_DEADLINE_SECONDS = 30.0


class ModelDeadlineExceeded(TimeoutError):
    """The lab's outer wall-clock limit for one model invocation expired."""


@dataclass(frozen=True)
class ModelTimeouts:
    """Effective local Bedrock transport settings."""

    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    model_deadline: float = DEFAULT_MODEL_DEADLINE_SECONDS


def resolve_model_timeouts(*, connect_timeout: float | None = None,
                           read_timeout: float | None = None,
                           max_attempts: int | None = None,
                           model_deadline: float | None = None,
                           environ: dict[str, str] | None = None) -> ModelTimeouts:
    """Resolve CLI-style overrides over environment values and local defaults."""
    env = os.environ if environ is None else environ

    def timeout_value(explicit, name, default):
        raw = explicit if explicit is not None else env.get(name, default)
        try:
            value = float(raw)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must be a number greater than 0 (got {raw!r})") from error
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be greater than 0 (got {raw!r})")
        return value

    raw_attempts = max_attempts if max_attempts is not None else env.get(
        "FOOTBALL_LAB_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
    try:
        attempts = int(raw_attempts)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"FOOTBALL_LAB_MAX_ATTEMPTS must be an integer of at least 1 (got {raw_attempts!r})"
        ) from error
    if attempts < 1:
        raise ValueError(
            f"FOOTBALL_LAB_MAX_ATTEMPTS must be at least 1 (got {raw_attempts!r})")
    return ModelTimeouts(
        timeout_value(connect_timeout, "FOOTBALL_LAB_CONNECT_TIMEOUT_SECONDS",
                      DEFAULT_CONNECT_TIMEOUT_SECONDS),
        timeout_value(read_timeout, "FOOTBALL_LAB_READ_TIMEOUT_SECONDS",
                      DEFAULT_READ_TIMEOUT_SECONDS),
        attempts,
        timeout_value(model_deadline, "FOOTBALL_LAB_MODEL_DEADLINE_SECONDS",
                      DEFAULT_MODEL_DEADLINE_SECONDS),
    )


@contextmanager
def model_deadline(seconds: float):
    """Interrupt synchronous model work after ``seconds`` on supported Linux hosts."""
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        raise RuntimeError("model deadline requires SIGALRM and signal.setitimer support")
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("model deadline must run in the main thread")

    def deadline_handler(_signum, _frame):
        raise ModelDeadlineExceeded(f"model invocation exceeded {seconds:.1f} seconds")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, deadline_handler)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)


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


def load_agent(team: str, role: str, root: Path | None = None,
               model_timeouts: ModelTimeouts | None = None):
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
    _replace_agent_model(module, role, model_timeouts or resolve_model_timeouts())
    return module


def _replace_agent_model(module, role: str, model_timeouts: ModelTimeouts,
                         system_prompt: str | None = None) -> None:
    """Apply lab-only Botocore settings without changing a stock source module."""
    from botocore.config import Config
    from strands import Agent
    from strands.models import BedrockModel

    client_config = Config(
        connect_timeout=model_timeouts.connect_timeout,
        read_timeout=model_timeouts.read_timeout,
        retries={"total_max_attempts": model_timeouts.max_attempts, "mode": "standard"},
    )
    model = BedrockModel(model_id=MODEL_IDS[role], boto_client_config=client_config)
    module.agent = Agent(model=model, system_prompt=system_prompt or module.SYSTEM_PROMPT)


def load_configured_agent(config, role: str, root: Path | None = None,
                          model_timeouts: ModelTimeouts | None = None):
    """Load a stock role and, only when requested, replace its model-facing prompt.

    The module, model ID, state summarizer, stock parser, command schema, and invocation
    path remain the same. An empty configuration returns the untouched stock module.
    """
    from tactical_config import tactical_addendum

    timeouts = model_timeouts or resolve_model_timeouts()
    module = load_agent(config.team, role, root, timeouts)
    addendum = tactical_addendum(config, role)
    if addendum:
        _replace_agent_model(module, role, timeouts, module.SYSTEM_PROMPT + addendum)
    return module


def invoke_stock_agent(module, payload: dict, clock: Callable[[], float], *,
                       deadline_seconds: float = DEFAULT_MODEL_DEADLINE_SECONDS) -> AgentCall:
    """Run the stock model, summarizer and parser without AgentCore transport."""
    from json_tolerant import parse_json_tolerant
    from parsing import VALID_COMMANDS, parse_commands
    from state import summarize_state

    game_state = payload["gameState"]
    team_id = payload.get("teamId", 0)
    # The selected stock role, not scenario ordering, determines the controlled player.
    player_id = module.MY_PLAYER_ID
    decision_start = clock()
    prompt = _summarize_with_team_relative_possession(
        summarize_state, game_state, team_id, player_id, module.POSITION_LABEL
    )
    model_start = clock()
    with model_deadline(deadline_seconds):
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


def _summarize_with_team_relative_possession(summarizer, game_state, team_id, player_id, label):
    """Correct only ambiguous possession text for current team-relative IDs.

    The current fixture repeats agentId_0..4 for each team, while ``possessionAgentId`` has no team
    component. Generated carriers are placed exactly at the ball, so nearest matching-ID geometry
    identifies the side. The stock helper remains untouched and continues producing the full prompt.
    """
    prompt = summarizer(game_state, team_id, player_id, label)
    ball = game_state.get("ball", {})
    possession_id = ball.get("possessionAgentId")
    if possession_id is None:
        return prompt
    candidates = [player for player in game_state.get("players", [])
                  if player.get("agentId") == possession_id]
    if len(candidates) < 2:
        return prompt
    ball_position = ball.get("position", {})
    holder = min(candidates, key=lambda candidate: math.dist(
        (candidate.get("position", {}).get("x", 0), candidate.get("position", {}).get("y", 0)),
        (ball_position.get("x", 0), ball_position.get("y", 0))))
    my_team_code = "home" if team_id == 0 else "away"
    side = "MY" if holder.get("teamCode") == my_team_code else "OPP"
    numeric_id = possession_id.rsplit("_", 1)[-1]
    current_side = "MY" if f"held by MY player {numeric_id}" in prompt else "OPP"
    prompt = prompt.replace(f"held by {current_side} player {numeric_id}",
                            f"held by {side} player {numeric_id}", 1)
    if numeric_id == str(player_id):
        prompt = prompt.replace(" hasBall=True", f" hasBall={side == 'MY'}", 1)
    return prompt


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
