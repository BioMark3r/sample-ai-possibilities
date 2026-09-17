import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.week2 import (INFRASTRUCTURE_PROBLEMS, Week2Store, analyze_state, candidate_config,
                       map_scenario_family, markdown_report, report_data, taxonomy_values, trends)


@pytest.fixture
def payload():
    return {"teamId": 0, "myPlayers": [3], "gameState": {"gameTime": 241.3,
        "score": {"home": 1, "away": 1}, "ball": {"position": {"x": 40, "y": 0},
        "isFree": False, "possessionAgentId": "agentId_3"}, "players": [
        {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 40, "y": 0}},
        {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 30, "y": 5}},
        {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 45, "y": 8}},
        {"agentId": "agentId_0", "teamCode": "away", "position": {"x": 52, "y": 0}},
        {"agentId": "agentId_3", "teamCode": "away", "position": {"x": 43, "y": 0}},
        {"agentId": "agentId_2", "teamCode": "away", "position": {"x": 20, "y": 4}}]}}


@pytest.fixture
def store(tmp_path):
    value=Week2Store(tmp_path/"week2"); value.new_match("week2-001", opponent="Rivals", final_score="1-1", configuration="baseline", git_sha="abc")
    return value


def test_match_initialization_and_directories(store):
    assert store._read("matches", "week2-001")["opponent"] == "Rivals"
    assert all((store.root/name).is_dir() for name in ("matches","observations","regressions","reports"))


def test_partial_observation_and_deterministic_id(store):
    one=store.observe("week2-001", "mid", "unnecessary_backward_pass", "high", notes="Passed back")
    two=store.observe("week2-001", "mid", "unnecessary_backward_pass", "high", notes="Passed back")
    assert one["observation_type"] == "partial" and one["observation_id"] == two["observation_id"]
    with pytest.raises(ValueError): store.observe("week2-001", problem_type="unknown")


def test_full_state_geometry_mapping_and_immutability(store, payload):
    original=deepcopy(payload)
    row=store.observe("week2-001", "fwd1", "missed_shooting_opportunity", "high", payload,
                      controlled_player_id=3, notes="passed")
    facts=row["analysis"]
    assert row["observation_type"] == "full_state"
    assert facts["controlled_player_possession"] is True
    assert facts["ball_zone"] == "attacking" and facts["score_state"] == "level"
    assert facts["match_time_bucket"] == "late" and facts["nearest_opponent"]["distance"] == 3
    assert facts["pressure_estimate"] == "high" and facts["distance_to_attacking_goal"] == 12.5
    assert facts["teammates_ahead_of_ball"] == 1 and facts["opponents_behind_ball"] == 1
    assert row["scenario_mapping"]["suggested_scenario_family"] == "shooting_opportunity"
    assert payload == original


def test_payload_validation_and_family_rules(store):
    row=store.observe("week2-001", "def", "poor_marking", payload={"gameState": {}}, notes="bad capture")
    assert row["observation_type"] == "partial" and row["payload_validation_errors"]
    with pytest.raises(ValueError): store.promote(row["observation_id"])
    assert map_scenario_family({"possession_side":"loose"})["suggested_scenario_family"] == "loose_ball"


def test_promotion_is_deterministic_and_preserves_payload(store, payload):
    obs=store.observe("week2-001", "fwd1", "missed_shooting_opportunity", "high", payload, notes="pass")
    one=store.promote(obs["observation_id"]); two=store.promote(obs["observation_id"])
    assert one == two and one["payload"] == payload
    assert one["metadata"]["scenario_id"].startswith("reg-")
    assert one["metadata"]["annotations"]["notes"] == "pass"


def test_taxonomy():
    assert {"missed_shooting_opportunity", "over_pressing", "positioning_issue", "throttled"} <= taxonomy_values()


def test_report_grouping_suggestions_and_infrastructure_separation(store):
    for note in ("a", "b"):
        store.observe("week2-001", "fwd1", "missed_shooting_opportunity", "high", notes=note)
    store.observe("week2-001", "def", "over_pressing", "low", notes="chased")
    infra=store.observe("week2-001", "mid", "throttled", "critical", notes="quota")
    data=report_data(store,"week2-001"); text=markdown_report(data)
    assert data["observation_count"] == 4 and len(data["tactical_observations"]) == 3
    assert data["infrastructure_observations"][0]["observation_id"] == infra["observation_id"]
    assert data["repeated_patterns"] == [{"role":"fwd1","problem_type":"missed_shooting_opportunity","count":2}]
    assert "shoot-vs-pass" in data["experiment_suggestions"][0]["recommendation"]
    assert text.index("HIGH") < text.index("LOW") and "Infrastructure (not tactical regressions)" in text
    with pytest.raises(ValueError): store.promote(infra["observation_id"])


def test_candidate_and_trends(store):
    store.observe("week2-001", "mid", "unnecessary_backward_pass", notes="one")
    config=candidate_config(store,"week2-001","unnecessary_backward_pass")
    assert config["candidate"] and config["review_required"] and list(config["roles"]) == ["mid"]
    store.new_match("week2-002")
    store.observe("week2-002", "mid", "unnecessary_backward_pass", notes="two")
    store.observe("week2-002", "gk", "timeout", notes="network")
    result=trends(store)
    assert result["problems"]["unnecessary_backward_pass"] == [1,1]
    assert "timeout" not in result["problems"] and "causality" in result["note"]
