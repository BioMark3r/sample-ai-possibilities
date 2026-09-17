import json, subprocess, sys
from pathlib import Path
import pytest
LAB = Path(__file__).parents[1]
sys.path.insert(0, str(LAB / "src"))
from preflight import check_preflight
from regression import ObservationError, import_observation, inspect_regression, validate_observation


def observation():
    payload = json.loads((LAB / "scenarios/basic_possession.json").read_text())
    return {"observation_id":"wk2-decision-1", "match_id":"official-week2-001", "role":"mid",
            "controlled_player_id":2, "observed_at":"2026-09-17T12:00:00Z", "gameTime":120.5,
            "score":{"home":1,"away":0}, "gameState":payload,
            "expected_behavior":"Pass into space", "observed_behavior":"Held possession",
            "notes":"Reconstructed from official log line 42", "tags":["week2","pressure"]}


def write_import(tmp_path, value=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source=tmp_path/"observation.json"; source.write_text(json.dumps(value or observation()))
    return import_observation(source, tmp_path/"regression")


def test_valid_import_is_deterministic_and_preserves_separate_metadata(tmp_path):
    first=write_import(tmp_path); second=write_import(tmp_path)
    assert first == second
    row=json.loads(first.read_text())
    assert row["regression_id"].startswith("wk2-decision-1-")
    assert row["metadata"]["notes"] == "Reconstructed from official log line 42"
    assert row["metadata"]["expected_behavior"] == "Pass into space"
    assert "notes" not in row["payload"]
    assert row["payload"]["gameState"]["players"]


def test_digest_changes_with_observation_and_malformed_rejected(tmp_path):
    one=write_import(tmp_path)
    changed=observation(); changed["observation_id"]="wk2-decision-2"
    two=write_import(tmp_path/"other", changed)
    assert one.name != two.name
    bad=observation(); del bad["expected_behavior"]
    assert "expected_behavior" in " ".join(validate_observation(bad))
    source=tmp_path/"bad.json"; source.write_text(json.dumps(bad))
    with pytest.raises(ObservationError, match="expected_behavior"): import_observation(source, tmp_path/"out")


def test_embedded_scenario_validation(tmp_path):
    bad=observation(); del bad["gameState"]["gameState"]["players"]
    source=tmp_path/"bad.json"; source.write_text(json.dumps(bad))
    with pytest.raises(ObservationError, match="players"): import_observation(source, tmp_path/"out")


def test_offline_inspection_reports_tactical_context(tmp_path):
    report=inspect_regression(write_import(tmp_path))
    assert report["role"] == "mid" and report["possession"] == "own"
    assert report["score_state"] == "leading" and report["ball_zone"] == "middle"
    assert report["nearest_opponents"] and report["nearest_teammates"]
    assert report["pressure_level"] in {"low","medium","high"}
    assert report["expected_behavior"] == "Pass into space"


def test_preflight_missing_credentials_is_offline_ready():
    class Session:
        region_name="us-east-1"
        def get_credentials(self): return None
    result=check_preflight(session_factory=Session)
    assert result["status"] == "OFFLINE READY"
    assert not result["aws"]["credentials"] and not result["live_benchmark_ready"]
    assert "AWS SDK credentials unavailable" in result["live_blockers"]


def test_replay_reports_model_boundary_failure_without_touching_regression(tmp_path):
    path=write_import(tmp_path); before=path.read_bytes()
    completed=subprocess.run([sys.executable, str(LAB/"replay_observation.py"),
                              "--scenario",str(path),"--team","not-a-team"], text=True, capture_output=True)
    assert completed.returncode == 1
    assert "LIVE REPLAY FAILED" in completed.stderr
    assert "regression remains valid" in completed.stderr
    assert path.read_bytes() == before
