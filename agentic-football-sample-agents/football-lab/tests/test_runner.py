import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

LAB = Path(__file__).parents[1]
sys.path.insert(0, str(LAB / "src"))
sys.path.insert(0, str(LAB.parents[0] / "lib"))
from adapters import AgentCall, invoke_stock_agent, load_agent
from runner import LocalAgent, ScenarioError, load_scenario, run
from validation import validate_commands

SCENARIO = LAB / "scenarios" / "basic_possession.json"
COMMAND = [{"commandType": "PASS", "playerId": 2, "teamId": 0,
            "parameters": {"target_player_id": 3, "type": "THROUGH"}}]


def module(player_id=2, label="MID", response=None):
    return SimpleNamespace(MY_PLAYER_ID=player_id, POSITION_LABEL=label,
                           agent=lambda _prompt: response or json.dumps(COMMAND))


def call(**overrides):
    values = dict(raw_output=json.dumps(COMMAND), commands=COMMAND, model_latency_ms=40,
                  parsing_latency_ms=2, decision_latency_ms=50, raw_strict_json=True,
                  raw_expected_structure=True, tolerant_recovery=False,
                  normalization={"player_id_overwritten": False})
    values.update(overrides)
    return AgentCall(**values)


def test_load_scenario():
    value = load_scenario(SCENARIO)
    assert value["gameState"]["players"]
    assert value["myPlayers"] == [2]


def test_agent_selection_rejects_unknown_values():
    for team, role in (("missing", "mid"), ("balanced", "coach")):
        with pytest.raises(ValueError):
            load_agent(team, role)


def test_stock_role_player_id_is_authoritative_with_all_players():
    payload = load_scenario(SCENARIO)
    payload["myPlayers"] = [4, 3, 2, 1, 0]
    roles = (("GK", 0), ("DEF", 1), ("MID", 2), ("FWD1", 3), ("FWD2", 4))
    for label, expected in roles:
        raw = json.dumps([{"commandType": "SET_STANCE", "playerId": 99,
                           "parameters": {"stance": 0}}])
        result = invoke_stock_agent(module(expected, label, raw), payload, __import__("time").perf_counter)
        assert result.commands[0]["playerId"] == expected


def test_command_validation_and_malformed_action():
    assert validate_commands(COMMAND).valid
    bad = [{"commandType": "PASS", "playerId": "two", "teamId": 0, "parameters": {}}]
    result = validate_commands(bad)
    assert not result.valid
    assert "target_player_id" in " ".join(result.errors)
    assert not validate_commands("PASS").valid


def test_malformed_scenario(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"gameState": {"ball": {}}}))
    with pytest.raises(ScenarioError, match="players"):
        load_scenario(path)


@pytest.mark.parametrize(
    ("raw", "strict", "structure", "recovered", "valid"),
    ((json.dumps(COMMAND), True, True, False, True),
     ('[{"commandType":"MOVE_TO","parameters":{"target_x":1,"target_y":2,"sprint":True}}]',
      False, True, True, True),
     ("not a command", False, False, False, False)),
)
def test_raw_compliance_and_post_parser_validity(raw, strict, structure, recovered, valid):
    payload = load_scenario(SCENARIO)
    result = invoke_stock_agent(module(response=raw), payload, __import__("time").perf_counter)
    assert result.raw_strict_json is strict
    assert result.raw_expected_structure is structure
    assert result.tolerant_recovery is recovered
    assert validate_commands(result.commands).valid is valid


def test_parser_normalization_is_visible():
    raw = json.dumps([
        {"commandType": "MOVE_TO", "playerId": 99,
         "parameters": {"target_x": 100, "target_y": -100, "sprint": False}},
        {"commandType": "PASS", "parameters": {"type": "GROUND"}},
        {"commandType": "DANCE", "parameters": {}},
    ])
    result = invoke_stock_agent(module(response=raw), load_scenario(SCENARIO),
                                __import__("time").perf_counter)
    assert result.normalization == {
        "player_id_overwritten": True,
        "team_id_added_or_overwritten": True,
        "missing_target_player_id_supplied": True,
        "move_coordinates_clamped": True,
        "unknown_commands_filtered": True,
    }


def test_warm_agent_reuses_loaded_module_and_reports_latency():
    loaded = []
    agent = LocalAgent("balanced", "mid", loader=lambda *_: loaded.append(1) or module(),
                       invoker=lambda *_: call())
    first = agent.run(load_scenario(SCENARIO))
    second = agent.run(load_scenario(SCENARIO))
    assert len(loaded) == 1
    assert first.player_id == second.player_id == 2
    assert first.decision_latency_ms == second.decision_latency_ms == 50
    assert first.model_latency_ms == 40
    assert first.parsing_latency_ms == 2
    assert first.validation_latency_ms is not None


def test_500ms_budget_uses_decision_not_cold_or_total_latency():
    slow_clock = iter((0.0, 1.0))
    agent = LocalAgent("balanced", "mid", loader=lambda *_: module(),
                       invoker=lambda *_: call(decision_latency_ms=499),
                       clock=lambda: next(slow_clock))
    agent._clock = __import__("time").perf_counter
    result = agent.run(load_scenario(SCENARIO))
    assert result.cold_start_ms == 1000
    assert result.exceeds_500ms is False

    agent._invoker = lambda *_: call(decision_latency_ms=501)
    assert agent.run(load_scenario(SCENARIO)).exceeds_500ms is True


def test_cold_run_serialization_includes_new_fields():
    result = run("balanced", "mid", SCENARIO, loader=lambda *_: module(),
                 invoker=lambda *_: call())
    data = json.loads(result.to_json())
    assert data["post_parser_valid"] is True
    assert data["valid_action"] is True
    for field in ("total_latency_ms", "cold_start_ms", "decision_latency_ms",
                  "model_latency_ms", "parsing_latency_ms", "validation_latency_ms"):
        assert field in data
