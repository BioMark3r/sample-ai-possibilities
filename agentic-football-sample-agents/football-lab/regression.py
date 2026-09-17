#!/usr/bin/env python3
"""Phase 3 named tactical configuration regression workflow."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from adapters import load_configured_agent
from analysis import compare_decisions, grouped_comparisons
from benchmarking import run_benchmark
from runner import LocalAgent
from scenario_generation import generate_corpus, load_corpus, write_corpus
from tactical_config import ROLES, load_config


def _csv(value):
    return {part.strip() for part in value.split(",") if part.strip()}


def filter_corpus(rows, filters):
    mapping = {"possession": "possession_team", "score": "score_state", "time": "time_remaining_bucket",
               "ball_zone": "ball_zone", "pressure": "pressure_level"}
    for argument, metadata in mapping.items():
        accepted = filters.get(argument)
        if accepted:
            rows = [row for row in rows if row["metadata"].get(metadata) in accepted]
    return rows


def _factory(config):
    return lambda _team, role: LocalAgent(config.team, role,
        loader=lambda _team, selected: load_configured_agent(config, selected))


def _highlights(metrics, threshold):
    values = {"different_action_type_pct": metrics["different_action_type_pct"],
              **{key: value for key, value in metrics["deltas"].items() if isinstance(value, (int, float))},
              **{f"tactical.{key}": value for key, value in metrics["deltas"]["tactical_rate_pct"].items()}}
    return [{"metric": key, "delta": value} for key, value in values.items()
            if value is not None and abs(value) >= threshold]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run baseline -> candidates -> deterministic paired report")
    parser.add_argument("--baseline", default="week2-baseline")
    parser.add_argument("--candidate", action="append", required=True, help="named config or JSON path; repeatable")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--corpus", help="consume an existing immutable JSONL corpus")
    source.add_argument("--generate", metavar="JSONL", help="generate and save one deterministic all-role corpus")
    parser.add_argument("--count", type=int, default=25, help="generated scenarios per role")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scenario-set", default="all")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--database", default="results/football_lab.sqlite")
    parser.add_argument("--output", default="results/regression.json")
    parser.add_argument("--possession", type=_csv)
    parser.add_argument("--score", type=_csv)
    parser.add_argument("--time", type=_csv)
    parser.add_argument("--ball-zone", type=_csv)
    parser.add_argument("--pressure", type=_csv)
    parser.add_argument("--highlight-threshold", type=float, default=20.0,
                        help="absolute percentage-point/ms threshold; descriptive, not a quality judgement")
    args = parser.parse_args(argv)
    if args.count < 1 or args.runs < 1:
        parser.error("--count and --runs must be positive")
    if args.generate:
        rows = [row for role in ROLES for row in generate_corpus(role, args.scenario_set, args.count, args.seed)]
        write_corpus(rows, args.generate)
        corpus_path = args.generate
    else:
        rows, corpus_path = load_corpus(args.corpus), args.corpus
    rows = filter_corpus(rows, vars(args))
    if not rows:
        parser.error("filters selected no scenarios")
    configs = [load_config(args.baseline), *[load_config(item) for item in args.candidate]]
    results = []
    for config in configs:
        role_benchmarks = []
        for role in ROLES:
            role_rows = [row for row in rows if row["metadata"]["role"] == role]
            if role_rows:
                role_benchmarks.append(run_benchmark(config.team, role, role_rows, args.runs,
                    agent_factory=_factory(config), corpus_path=corpus_path, database=args.database,
                    configuration=config))
        results.append({"config": config, "benchmarks": role_benchmarks,
                        "decisions": [d for b in role_benchmarks for d in b["decisions"]]})
    baseline = results[0]
    comparisons = []
    for candidate in results[1:]:
        metrics = compare_decisions(baseline["decisions"], candidate["decisions"])
        comparisons.append({"baseline": baseline["config"].name, "candidate": candidate["config"].name,
                            "metrics": metrics, "by_role_and_family": grouped_comparisons(
                                baseline["decisions"], candidate["decisions"]),
                            "large_changes": _highlights(metrics, args.highlight_threshold)})
    document = {"schema_version": 3, "corpus": str(corpus_path), "filters": {
                    key: sorted(value) if value else None for key, value in vars(args).items()
                    if key in {"possession", "score", "time", "ball_zone", "pressure"}},
                "configurations": [{"configuration": item["config"].to_dict(),
                    "benchmarks": [{k: bench[k] for k in ("benchmark_id", "role", "corpus_sha256", "summary")}
                                   for bench in item["benchmarks"]]} for item in results],
                "comparisons": comparisons,
                "interpretation": "Large changes are threshold highlights only; they are not labeled good or bad."}
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, indent=2))
    return document


if __name__ == "__main__":
    main()
