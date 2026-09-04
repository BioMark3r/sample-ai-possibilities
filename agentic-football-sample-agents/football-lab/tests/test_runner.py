import json
import sys
from pathlib import Path
from types import SimpleNamespace

LAB = Path(__file__).parents[1]
sys.path.insert(0, str(LAB / "src"))
from adapters import AgentCall, load_agent
from runner import ScenarioError, load_scenario, run
from validation import validate_commands

SCENARIO = LAB / "scenarios" / "basic_possession.json"


def test_load_scenario():
    value = load_scenario(SCENARIO)
    assert value["gameState"]["players"]
    assert value["myPlayers"] == [2]


def test_agent_selection_rejects_unknown_values():
    for team, role in (("missing", "mid"), ("balanced", "coach")):
        try:
            load_agent(team, role)
        except ValueError:
            pass
        else:
            raise AssertionError("unknown selection should fail before importing dependencies")


def test_command_validation_and_malformed_action():
    good = [{"commandType": "PASS", "playerId": 2, "teamId": 0,
             "parameters": {"target_player_id": 3, "type": "GROUND"}}]
    assert validate_commands(good).valid
    bad = [{"commandType": "PASS", "playerId": "two", "teamId": 0, "parameters": {}}]
    result = validate_commands(bad)
    assert not result.valid
    assert "target_player_id" in " ".join(result.errors)
    assert not validate_commands("PASS").valid


def test_malformed_scenario(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"gameState": {"ball": {}}}))
    try:
        load_scenario(path)
    except ScenarioError as error:
        assert "players" in str(error)
    else:
        raise AssertionError("malformed scenario was accepted")


def test_latency_result_serialization():
    times = iter((1.0, 1.1))
    command = [{"commandType": "PASS", "playerId": 2, "teamId": 0,
                "parameters": {"target_player_id": 3, "type": "THROUGH"}}]
    result = run("balanced", "mid", SCENARIO,
                 loader=lambda *_: SimpleNamespace(),
                 invoker=lambda *_: AgentCall("[]", command, 42.5, False),
                 clock=lambda: next(times))
    data = json.loads(result.to_json())
    assert data["valid_action"] is True
    assert round(data["latency_ms"]) == 100
    assert data["model_latency_ms"] == 42.5
    assert data["exceeds_500ms"] is False
