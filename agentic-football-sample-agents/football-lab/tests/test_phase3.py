import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

LAB = Path(__file__).parents[1]
sys.path.insert(0, str(LAB / "src"))
from adapters import load_configured_agent
from analysis import grouped_comparisons
from regression import filter_corpus
from scenario_generation import generate_corpus
from tactical_config import load_config, tactical_addendum


def write_config(tmp_path, document):
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(document))
    return path


def test_configuration_parsing_and_role_override_merge(tmp_path):
    path = write_config(tmp_path, {"name": "test", "team": "balanced",
        "global": {"instructions": ["Keep compact."], "parameters": {"tempo": "normal", "press": .4}},
        "roles": {"def": {"instructions": ["Engage earlier."], "parameters": {"press": .8}}}})
    config = load_config(path)
    assert config.settings_for("mid") == {"instructions": ["Keep compact."],
                                           "parameters": {"tempo": "normal", "press": .4}}
    assert config.settings_for("def") == {"instructions": ["Keep compact.", "Engage earlier."],
                                           "parameters": {"tempo": "normal", "press": .8}}
    assert "press: 0.8" in tactical_addendum(config, "def")


@pytest.mark.parametrize("change", [{"roles": {"coach": {}}},
    {"global": {"instructions": "not-a-list"}}, {"team": "extremely-aggressive"}])
def test_configuration_rejects_invalid_documents(tmp_path, change):
    document = {"name": "bad", "team": "balanced", "global": {}, "roles": {}}
    document.update(change)
    with pytest.raises(ValueError):
        load_config(write_config(tmp_path, document))


def test_week2_baseline_has_no_prompt_or_agent_path_change(monkeypatch):
    config = load_config("week2-baseline")
    original = object()
    stock = SimpleNamespace(SYSTEM_PROMPT="stock prompt", agent=original)
    monkeypatch.setattr("adapters.load_agent", lambda *_: stock)
    assert tactical_addendum(config, "gk") == ""
    assert load_configured_agent(config, "gk") is stock
    assert stock.SYSTEM_PROMPT == "stock prompt"
    assert stock.agent is original


def _decision(row, action):
    return {"scenario_id": row["metadata"]["scenario_id"], "run_index": 0,
            "role": row["metadata"]["role"], "scenario_metadata": row["metadata"],
            "action_type": action, "post_parser_valid": True, "raw_strict_json": True,
            "tolerant_recovery": False, "parser_normalization": {}, "exception": None,
            "exceeds_500ms": False, "decision_latency_ms": 10, "model_latency_ms": 8}


def test_deterministic_paired_role_family_comparison():
    corpus = generate_corpus("fwd1", "shooting_opportunity", 2, 42)
    left = [_decision(row, "PASS") for row in corpus]
    right = [_decision(row, "SHOOT") for row in corpus]
    assert grouped_comparisons(left, right) == grouped_comparisons(left, right)
    metric = grouped_comparisons(left, right)["fwd1:shooting_opportunity"]
    assert metric["matched_decisions"] == 2
    assert metric["different_action_type_pct"] == 100
    assert metric["right"]["shoot_rate_pct"] == 100


def test_all_supported_filters_compose():
    row = generate_corpus("mid", "under_pressure", 1, 7)[0]
    metadata = row["metadata"]
    filters = {"possession": {metadata["possession_team"]}, "score": {metadata["score_state"]},
               "time": {metadata["time_remaining_bucket"]}, "ball_zone": {metadata["ball_zone"]},
               "pressure": {metadata["pressure_level"]}}
    assert filter_corpus([row], filters) == [row]
    filters["pressure"] = {"not-present"}
    assert filter_corpus([row], filters) == []
