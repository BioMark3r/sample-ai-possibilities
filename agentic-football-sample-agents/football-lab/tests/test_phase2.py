import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

LAB = Path(__file__).parents[1]
sys.path.insert(0, str(LAB / "src"))
sys.path.insert(0, str(LAB.parents[0] / "lib"))
from adapters import AgentCall, TEAMS, _summarize_with_team_relative_possession
from analysis import compare_decisions, percentile, summarize
from benchmarking import run_benchmark
from runner import LocalAgent, ScenarioError
from scenario_generation import (EARLY_END_SECONDS, FAMILIES, LATE_START_SECONDS,
                                 MATCH_DURATION_SECONDS, NORMAL_PLAY_MODE,
                                 generate_corpus, load_corpus, write_corpus)
from state import summarize_state


COMMAND = [{"commandType": "PASS", "playerId": 2, "teamId": 0,
            "parameters": {"target_player_id": 3, "type": "THROUGH"}}]


def fake_factory(loads):
    def loader(team, role):
        loads.append((team, role))
        return SimpleNamespace(MY_PLAYER_ID=2, POSITION_LABEL="MID")
    def invoker(*_):
        return AgentCall(json.dumps(COMMAND), COMMAND, 10, 1, 12, True, True, False,
                         {"player_id_overwritten": False})
    return lambda team, role: LocalAgent(team, role, loader=loader, invoker=invoker)


def test_deterministic_generation_and_seed_changes(tmp_path):
    first = generate_corpus("mid", "all", 20, 42)
    second = generate_corpus("mid", "all", 20, 42)
    changed = generate_corpus("mid", "all", 20, 43)
    assert first == second
    assert first != changed
    one, two = tmp_path / "one.jsonl", tmp_path / "two.jsonl"
    write_corpus(first, one); write_corpus(second, two)
    assert one.read_bytes() == two.read_bytes()


def test_generated_schema_and_ranges(tmp_path):
    rows = generate_corpus("mid", "all", len(FAMILIES), 9)
    assert {row["metadata"]["scenario_family"] for row in rows} == set(FAMILIES)
    for row in rows:
        assert set(row) == {"metadata", "payload"}
        metadata, state = row["metadata"], row["payload"]["gameState"]
        assert metadata["controlled_player_id"] == 2
        assert len(state["players"]) == 10
        assert 0 <= state["gameTime"] <= MATCH_DURATION_SECONDS
        assert state["playMode"] == NORMAL_PLAY_MODE
        assert -55 <= state["ball"]["position"]["x"] <= 55
        assert -35 <= state["ball"]["position"]["y"] <= 35
        assert all(-55 <= p["position"]["x"] <= 55 and -35 <= p["position"]["y"] <= 35 for p in state["players"])
    path = tmp_path / "corpus.jsonl"; write_corpus(rows, path)
    assert load_corpus(path) == rows


def _family(name, seed=9):
    return generate_corpus("mid", name, 1, seed)[0]


def _players(row, team):
    return [player for player in row["payload"]["gameState"]["players"] if player["teamCode"] == team]


def _distance(left, right):
    return ((left["x"] - right["x"]) ** 2 + (left["y"] - right["y"]) ** 2) ** .5


def test_time_buckets_cover_five_minute_match_and_late_means_near_end():
    rows = generate_corpus("mid", "all", 30, 51)
    by_bucket = {name: [] for name in ("early", "middle", "late")}
    for row in rows:
        by_bucket[row["metadata"]["time_remaining_bucket"]].append(row["payload"]["gameState"]["gameTime"])
    assert all(by_bucket.values())
    assert all(time < EARLY_END_SECONDS for time in by_bucket["early"])
    assert all(EARLY_END_SECONDS <= time < LATE_START_SECONDS for time in by_bucket["middle"])
    assert all(LATE_START_SECONDS <= time <= MATCH_DURATION_SECONDS for time in by_bucket["late"])
    assert all(MATCH_DURATION_SECONDS - time <= 75 for time in by_bucket["late"])


def test_possession_is_settled_with_moderate_pressure():
    row = _family("possession")
    state = row["payload"]["gameState"]
    ball = state["ball"]["position"]
    assert row["metadata"]["possession_team"] == "home"
    assert state["ball"]["velocity"]["x"] <= .5
    assert 6 <= min(_distance(player["position"], ball) for player in _players(row, "away")) <= 10


def test_transition_attack_has_forward_support_and_unset_opponents():
    row = _family("transition_attack")
    state = row["payload"]["gameState"]
    ball_x = state["ball"]["position"]["x"]
    controlled = next(p for p in _players(row, "home") if p["agentId"] == "agentId_2")
    assert row["metadata"]["possession_team"] == "home"
    assert state["ball"]["velocity"]["x"] > 0
    assert any(p["position"]["x"] >= controlled["position"]["x"] + 10 for p in _players(row, "home"))
    assert sum(p["position"]["x"] < ball_x for p in _players(row, "away")) >= 3


def test_transition_defense_has_advancing_opponent_and_recovery_geometry():
    row = _family("transition_defense")
    state = row["payload"]["gameState"]
    ball_x = state["ball"]["position"]["x"]
    controlled = next(p for p in _players(row, "home") if p["agentId"] == "agentId_2")
    assert row["metadata"]["possession_team"] == "away"
    assert state["ball"]["velocity"]["x"] < 0
    assert controlled["position"]["x"] > ball_x
    assert any(p["position"]["x"] < ball_x for p in _players(row, "away"))
    assert sum(p["position"]["x"] > ball_x for p in _players(row, "home")) >= 3


def test_under_pressure_has_close_opponent_and_viable_outlets():
    row = _family("under_pressure")
    ball = row["payload"]["gameState"]["ball"]["position"]
    assert row["payload"]["gameState"]["ball"]["possessionAgentId"] == "agentId_2"
    assert min(_distance(player["position"], ball) for player in _players(row, "away")) < 4
    assert sum(8 <= _distance(player["position"], ball) <= 20 for player in _players(row, "home")) >= 2


def test_shooting_opportunity_has_constrained_envelope_and_goal_context():
    row = _family("shooting_opportunity")
    state = row["payload"]["gameState"]
    ball = state["ball"]["position"]
    assert state["ball"]["possessionAgentId"] == "agentId_2"
    assert 13 <= _distance(ball, {"x": 55, "y": 0}) <= 28
    assert abs(ball["y"]) <= 12
    assert any(p["agentId"] == "agentId_0" and p["position"]["x"] >= 50 for p in _players(row, "away"))
    assert any(ball["x"] < p["position"]["x"] < 55 for p in _players(row, "away"))


def test_loose_ball_is_free_and_both_sides_contest_it():
    row = _family("loose_ball")
    ball_state = row["payload"]["gameState"]["ball"]
    ball = ball_state["position"]
    assert ball_state["isFree"] and ball_state["possessionAgentId"] is None
    assert min(_distance(p["position"], ball) for p in _players(row, "home")) <= 4.2
    assert min(_distance(p["position"], ball) for p in _players(row, "away")) <= 4.2


def test_defensive_shape_is_settled_and_organized_not_transition_geometry():
    shaped = _family("defensive_shape")
    transition = _family("transition_defense")
    ball_x = shaped["payload"]["gameState"]["ball"]["position"]["x"]
    outfield_x = sorted(p["position"]["x"] for p in _players(shaped, "home") if p["agentId"] != "agentId_0")
    assert shaped["metadata"]["possession_team"] == "away"
    assert all(x < ball_x for x in outfield_x)
    assert max(outfield_x) - min(outfield_x) >= 15
    assert abs(shaped["payload"]["gameState"]["ball"]["velocity"]["x"]) <= .5
    assert transition["payload"]["gameState"]["ball"]["velocity"]["x"] < -1.5


@pytest.mark.parametrize(("family", "expected"),
                         (("under_pressure", "held by MY player 2"),
                          ("transition_defense", "held by OPP player"),
                          ("loose_ball", "held by free")))
def test_real_shared_summarizer_identifies_generated_possession(family, expected):
    row = _family(family)
    prompt = _summarize_with_team_relative_possession(
        summarize_state, row["payload"]["gameState"], 0, 2, "MID"
    )
    assert expected in prompt


def test_opponent_possession_prompt_uses_runtime_team_relative_ids():
    row = _family("transition_defense", seed=27)
    state = row["payload"]["gameState"]
    prompt = _summarize_with_team_relative_possession(summarize_state, state, 0, 2, "MID")
    possessing_id = state["ball"]["possessionAgentId"].removeprefix("agentId_")
    assert f"Ball: ({state['ball']['position']['x']:.1f}, {state['ball']['position']['y']:.1f}) " \
           f"held by OPP player {possessing_id}" in prompt
    opponents = prompt.split("Opponents:", 1)[1]
    assert [line.strip().split(":", 1)[0] for line in opponents.splitlines() if line.startswith("  P")] == \
           ["P0", "P1", "P2", "P3", "P4"]
    assert all(player["agentId"] in {f"agentId_{index}" for index in range(5)}
               for player in state["players"])
    assert "P5" not in prompt and "P9" not in prompt


def test_benchmark_warm_reuse_multi_run_persistence_and_summary(tmp_path):
    corpus = generate_corpus("mid", "transition", 3, 42)
    loads = []
    database, output = tmp_path / "lab.sqlite", tmp_path / "result.json"
    result = run_benchmark("balanced", "mid", corpus, 3, agent_factory=fake_factory(loads),
                           output=output, database=database)
    assert loads == [("balanced", "mid")]
    assert len(result["decisions"]) == 9
    assert {row["run_index"] for row in result["decisions"]} == {0, 1, 2}
    assert result["summary"]["total_decisions"] == 9
    assert result["summary"]["valid_post_parser_pct"] == 100
    assert result["summary"]["action_distribution"] == {"PASS": 9}
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM benchmarks").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM scenarios").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM decisions").fetchone()[0] == 9
    assert json.loads(output.read_text())["benchmark_id"] == result["benchmark_id"]


def test_percentiles_and_identical_scenario_comparison():
    assert percentile(range(1, 101), 50) == 50
    assert percentile(range(1, 101), 95) == 95
    assert percentile([], 50) is None
    base = {"run_index": 0, "exception": None, "parser_normalization": {}, "scenario_metadata": {"scenario_family": "possession"}}
    left = [{**base, "scenario_id": "a", "action_type": "PASS"}, {**base, "scenario_id": "b", "action_type": "SHOOT"}]
    right = [{**base, "scenario_id": "a", "action_type": "PASS"}, {**base, "scenario_id": "b", "action_type": "MARK"}]
    result = compare_decisions(left, right)
    assert result["matched_decisions"] == 2
    assert result["same_action_type_pct"] == result["different_action_type_pct"] == 50
    assert result["left"]["shoot_rate_pct"] == 50
    assert summarize(left)["breakdowns"]["None:possession"]["total"] == 2


def test_team_variants_are_explicit_and_infrastructure_variants_excluded():
    assert set(TEAMS) == {"balanced", "extremely-aggressive", "extremely-defensive"}


@pytest.mark.parametrize("contents", ("", "not-json\n", '{"metadata":{},"payload":{}}\n'))
def test_malformed_corpus(contents, tmp_path):
    path = tmp_path / "bad.jsonl"; path.write_text(contents)
    with pytest.raises(ScenarioError):
        load_corpus(path)
