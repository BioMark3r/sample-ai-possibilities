import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

LAB = Path(__file__).parents[1]
sys.path.insert(0, str(LAB / "src"))
from adapters import AgentCall, TEAMS
from analysis import compare_decisions, percentile, summarize
from benchmarking import run_benchmark
from runner import LocalAgent, ScenarioError
from scenario_generation import FAMILIES, generate_corpus, load_corpus, write_corpus


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
        assert -55 <= state["ball"]["position"]["x"] <= 55
        assert -35 <= state["ball"]["position"]["y"] <= 35
        assert all(-55 <= p["position"]["x"] <= 55 and -35 <= p["position"]["y"] <= 35 for p in state["players"])
    path = tmp_path / "corpus.jsonl"; write_corpus(rows, path)
    assert load_corpus(path) == rows


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
