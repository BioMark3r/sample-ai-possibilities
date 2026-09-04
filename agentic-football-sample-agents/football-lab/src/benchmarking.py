"""Benchmark orchestration kept separate from generation, storage, and analysis."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from analysis import summarize
from experiment_store import ExperimentStore
from runner import LocalAgent
from scenario_generation import load_corpus


def run_benchmark(team, role, scenarios, runs=1, *, agent_factory=LocalAgent,
                  corpus_path=None, output=None, database=None):
    if runs < 1:
        raise ValueError("runs must be positive")
    corpus = load_corpus(scenarios) if isinstance(scenarios, (str, Path)) else scenarios
    canonical = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in corpus)
    created = datetime.now(timezone.utc).isoformat()
    benchmark_id = f"bench-{uuid.uuid4().hex[:12]}"
    agent = agent_factory(team, role)  # exactly one warm instance per configuration
    decisions = []
    for scenario in corpus:
        for run_index in range(runs):
            result = agent.run(scenario["payload"], scenario_name=scenario["metadata"]["scenario_id"])
            raw = result.to_dict()
            decisions.append({"benchmark_id": benchmark_id, "scenario_id": scenario["metadata"]["scenario_id"],
                "team": team, "role": role, "player_id": result.player_id, "run_index": run_index,
                "action_type": raw["action_type"], "action": raw["action"],
                **{key: raw[key] for key in ("post_parser_valid", "raw_strict_json", "raw_expected_structure",
                    "tolerant_recovery", "parser_normalization", "total_latency_ms", "decision_latency_ms",
                    "model_latency_ms", "parsing_latency_ms", "validation_latency_ms", "exceeds_500ms", "exception")},
                "timestamp": datetime.now(timezone.utc).isoformat(), "scenario_metadata": scenario["metadata"]})
    document = {"schema_version": 1, "benchmark_id": benchmark_id, "created_at": created, "team": team,
                "role": role, "runs": runs, "corpus_path": str(corpus_path or scenarios) if isinstance(scenarios, (str, Path)) else corpus_path,
                "corpus_sha256": hashlib.sha256(canonical.encode()).hexdigest(), "summary": summarize(decisions),
                "decisions": decisions}
    if output:
        path = Path(output); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if database:
        store = ExperimentStore(database)
        try: store.save(document, corpus, decisions)
        finally: store.close()
    return document
