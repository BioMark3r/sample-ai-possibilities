"""Non-destructive local and AWS readiness checks."""
from __future__ import annotations
import importlib.util, os, platform
from pathlib import Path

def check_preflight(*, session_factory=None):
    lab = Path(__file__).parents[1]
    result = {"python_runtime": {"ok": tuple(map(int, platform.python_version_tuple()[:2])) >= (3, 10), "version": platform.python_version()},
              "dependencies": {}, "scenario_generation": False, "offline_regression_tooling": False,
              "aws": {"credentials": False, "identity": None, "region": None},
              "bedrock_model_invocation": {"ready": False, "checked": False, "detail": "not checked: preflight performs no model calls"}}
    for package in ("pytest", "strands", "boto3"):
        result["dependencies"][package] = importlib.util.find_spec(package) is not None
    try:
        from scenario_generation import generate_corpus
        result["scenario_generation"] = bool(generate_corpus("mid", "possession", 1, 1))
        from regression import validate_observation  # noqa: F401
        result["offline_regression_tooling"] = True
    except Exception as error: result["local_error"] = f"{type(error).__name__}: {error}"
    if result["dependencies"]["boto3"]:
        try:
            if session_factory is None:
                import boto3
                session_factory = boto3.Session
            session = session_factory()
            result["aws"]["region"] = session.region_name or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
            credentials = session.get_credentials()
            result["aws"]["credentials"] = credentials is not None
            if credentials:
                result["aws"]["identity"] = session.client("sts").get_caller_identity()
        except Exception as error: result["aws"]["error"] = f"{type(error).__name__}: {error}"
    offline = result["python_runtime"]["ok"] and result["scenario_generation"] and result["offline_regression_tooling"]
    live_prerequisites = offline and result["dependencies"].get("strands") and result["aws"]["credentials"] and result["aws"]["identity"] and result["aws"]["region"]
    live = live_prerequisites and result["bedrock_model_invocation"]["ready"]
    result["status"] = "LIVE MODEL READY" if live else "OFFLINE READY" if offline else "BLOCKED"
    blockers=[]
    if not offline: blockers.append("local runtime/tooling check failed")
    if not result["dependencies"].get("strands"): blockers.append("strands-agents dependency unavailable")
    if not result["aws"]["credentials"]: blockers.append("AWS SDK credentials unavailable")
    if result["aws"]["credentials"] and not result["aws"]["identity"]: blockers.append("AWS identity lookup failed")
    if not result["aws"]["region"]: blockers.append("AWS region not configured")
    if live_prerequisites and not result["bedrock_model_invocation"]["ready"]: blockers.append("Bedrock invocation capability not verified (no model call performed)")
    result["live_benchmark_ready"] = bool(live); result["live_blockers"] = blockers
    return result
