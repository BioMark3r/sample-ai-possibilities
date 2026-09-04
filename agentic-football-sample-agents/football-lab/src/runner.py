"""Scenario loading, execution, timing, and result serialization."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from adapters import invoke_stock_agent, load_agent
from validation import validate_commands, validate_scenario


class ScenarioError(ValueError):
    pass


@dataclass
class RunResult:
    team: str; agent: str; scenario: str
    action: list[dict] | None; valid_action: bool; action_type: str | None
    details: dict; validation_errors: list[str]; malformed_model_output: bool
    latency_ms: float; model_latency_ms: float | None; exceeds_500ms: bool; timed_out: bool
    exception: str | None

    def to_dict(self):
        return asdict(self)

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2)


def load_scenario(path: str | Path) -> dict:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScenarioError(f"Could not load scenario {path}: {error}") from error
    errors = validate_scenario(value)
    if errors:
        raise ScenarioError("Invalid scenario: " + "; ".join(errors))
    return value


def run(team: str, role: str, scenario_path: str | Path, *, loader=load_agent,
        invoker=invoke_stock_agent, clock: Callable[[], float] = time.perf_counter) -> RunResult:
    started = clock()
    action = None; model_ms = None; malformed = False; error = None; timed_out = False
    validation = validate_commands(action)
    try:
        payload = load_scenario(scenario_path)
        module = loader(team, role)
        call = invoker(module, payload, clock)
        action, model_ms, malformed = call.commands, call.model_latency_ms, call.malformed_model_output
        validation = validate_commands(action)
    except Exception as exception:  # result contract intentionally reports local/AWS failures
        error = f"{type(exception).__name__}: {exception}"
        timed_out = isinstance(exception, TimeoutError) or "timeout" in type(exception).__name__.lower()
    latency = (clock() - started) * 1000
    return RunResult(team, role.upper(), Path(scenario_path).stem, action, validation.valid,
                     validation.action_type, validation.details, validation.errors, malformed,
                     latency, model_ms, latency > 500, timed_out, error)


def format_text(result: RunResult) -> str:
    action = json.dumps(result.action, indent=2) if result.action is not None else "none"
    lines = [f"Team: {result.team}", f"Agent: {result.agent}",
             f"Scenario: {result.scenario}", "", "Action:", action, "",
             f"Latency: {result.latency_ms:.0f} ms"]
    if result.model_latency_ms is not None:
        lines.append(f"Model latency: {result.model_latency_ms:.0f} ms")
    lines.extend((f"Exceeds 500 ms: {'YES' if result.exceeds_500ms else 'NO'}",
                  f"Timed out: {'YES' if result.timed_out else 'NO'}",
                  f"Valid action: {'YES' if result.valid_action else 'NO'}",
                  f"Malformed model output: {'YES' if result.malformed_model_output else 'NO'}",
                  f"Exception: {result.exception or 'none'}"))
    return "\n".join(lines)
