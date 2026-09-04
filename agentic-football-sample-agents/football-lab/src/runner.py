"""Scenario loading, warm-agent execution, timing, and result serialization."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from adapters import invoke_stock_agent, load_agent
from validation import Validation, validate_commands, validate_scenario


class ScenarioError(ValueError):
    pass


@dataclass
class RunResult:
    team: str
    agent: str
    player_id: int | None
    scenario: str
    action: list[dict] | None = None
    post_parser_valid: bool = False
    action_type: str | None = None
    details: dict = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)
    raw_strict_json: bool = False
    raw_expected_structure: bool = False
    tolerant_recovery: bool = False
    parser_normalization: dict[str, bool] = field(default_factory=dict)
    total_latency_ms: float = 0.0
    cold_start_ms: float = 0.0
    decision_latency_ms: float | None = None
    model_latency_ms: float | None = None
    parsing_latency_ms: float | None = None
    validation_latency_ms: float | None = None
    exceeds_500ms: bool = False
    timed_out: bool = False
    exception: str | None = None

    @property
    def valid_action(self) -> bool:
        """Compatibility alias for the original Phase 1 result field."""
        return self.post_parser_valid

    def to_dict(self):
        value = asdict(self)
        value["valid_action"] = self.valid_action
        return value

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2)


def load_scenario(path: str | Path) -> dict:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScenarioError(f"Could not load scenario {path}: {error}") from error
    _validate_scenario_or_raise(value)
    return value


def _validate_scenario_or_raise(value: dict) -> None:
    errors = validate_scenario(value)
    if errors:
        raise ScenarioError("Invalid scenario: " + "; ".join(errors))


class LocalAgent:
    """A reusable, already-loaded stock role for repeated local decisions."""

    def __init__(self, team: str, role: str, *, loader=load_agent,
                 invoker=invoke_stock_agent, clock: Callable[[], float] = time.perf_counter):
        self.team = team.lower()
        self.role = role.lower()
        self._clock = clock
        self._invoker = invoker
        started = clock()
        self.module = loader(self.team, self.role)
        self.cold_start_ms = (clock() - started) * 1000
        self.player_id = self.module.MY_PLAYER_ID

    def run(self, scenario: dict | str | Path, *, scenario_name: str | None = None) -> RunResult:
        """Invoke one scenario without re-importing/reinitializing the stock agent."""
        total_started = self._clock()
        name = scenario_name or (Path(scenario).stem if not isinstance(scenario, dict) else "scenario")
        try:
            payload = load_scenario(scenario) if not isinstance(scenario, dict) else scenario
            if isinstance(scenario, dict):
                _validate_scenario_or_raise(payload)
                name = scenario_name or payload.get("name", "scenario")
            call = self._invoker(self.module, payload, self._clock)
            validation_started = self._clock()
            validation = validate_commands(call.commands)
            validation_ms = (self._clock() - validation_started) * 1000
            total_ms = (self._clock() - total_started) * 1000
            return RunResult(
                team=self.team, agent=self.module.POSITION_LABEL, player_id=self.player_id,
                scenario=name, action=call.commands, post_parser_valid=validation.valid,
                action_type=validation.action_type, details=validation.details,
                validation_errors=validation.errors, raw_strict_json=call.raw_strict_json,
                raw_expected_structure=call.raw_expected_structure,
                tolerant_recovery=call.tolerant_recovery,
                parser_normalization=call.normalization, total_latency_ms=total_ms,
                cold_start_ms=self.cold_start_ms, decision_latency_ms=call.decision_latency_ms,
                model_latency_ms=call.model_latency_ms, parsing_latency_ms=call.parsing_latency_ms,
                validation_latency_ms=validation_ms,
                exceeds_500ms=call.decision_latency_ms > 500,
            )
        except Exception as exception:  # result contract intentionally reports local/AWS failures
            total_ms = (self._clock() - total_started) * 1000
            return _error_result(self.team, self.role, self.player_id, name, total_ms,
                                 self.cold_start_ms, exception)


def run(team: str, role: str, scenario_path: str | Path, *, loader=load_agent,
        invoker=invoke_stock_agent, clock: Callable[[], float] = time.perf_counter) -> RunResult:
    """Cold single-scenario convenience API used by the CLI."""
    total_started = clock()
    try:
        agent = LocalAgent(team, role, loader=loader, invoker=invoker, clock=clock)
        result = agent.run(scenario_path)
        result.total_latency_ms = (clock() - total_started) * 1000
        return result
    except Exception as exception:
        total_ms = (clock() - total_started) * 1000
        return _error_result(team, role, None, Path(scenario_path).stem, total_ms, 0.0, exception)


def _error_result(team, role, player_id, scenario, total_ms, cold_ms, exception) -> RunResult:
    validation: Validation = validate_commands(None)
    timed_out = isinstance(exception, TimeoutError) or "timeout" in type(exception).__name__.lower()
    return RunResult(
        team=team, agent=role.upper(), player_id=player_id, scenario=scenario,
        validation_errors=validation.errors, total_latency_ms=total_ms,
        cold_start_ms=cold_ms, timed_out=timed_out,
        exception=f"{type(exception).__name__}: {exception}",
    )


def format_text(result: RunResult) -> str:
    action = json.dumps(result.action, indent=2) if result.action is not None else "none"
    lines = [f"Team: {result.team}", f"Agent: {result.agent} (player {result.player_id})",
             f"Scenario: {result.scenario}", "", "Action:", action, "",
             f"Total/cold-run latency: {result.total_latency_ms:.0f} ms",
             f"Agent initialization: {result.cold_start_ms:.0f} ms"]
    for label, value in (("Decision latency", result.decision_latency_ms),
                         ("Model latency", result.model_latency_ms),
                         ("Parsing latency", result.parsing_latency_ms),
                         ("Validation latency", result.validation_latency_ms)):
        lines.append(f"{label}: {value:.0f} ms" if value is not None else f"{label}: unavailable")
    lines.extend((f"Decision exceeds 500 ms: {'YES' if result.exceeds_500ms else 'NO'}",
                  f"Raw strict JSON: {'YES' if result.raw_strict_json else 'NO'}",
                  f"Raw expected structure: {'YES' if result.raw_expected_structure else 'NO'}",
                  f"Tolerant recovery: {'YES' if result.tolerant_recovery else 'NO'}",
                  f"Post-parser valid: {'YES' if result.post_parser_valid else 'NO'}",
                  f"Parser normalization: {json.dumps(result.parser_normalization, sort_keys=True)}",
                  f"Timed out: {'YES' if result.timed_out else 'NO'}",
                  f"Exception: {result.exception or 'none'}"))
    return "\n".join(lines)
