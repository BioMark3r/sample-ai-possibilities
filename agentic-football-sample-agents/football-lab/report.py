#!/usr/bin/env python3
"""Render benchmark or comparison JSON as concise Markdown."""
import argparse
import json
from pathlib import Path


def pct(value): return f"{value:.1f}%"


def benchmark_report(value):
    summary = value["summary"]
    lines = [f"# {value['team'].replace('-', ' ').title()} {value['role'].upper()} benchmark", "",
             f"**{summary['total_decisions']} decisions**", "", "| Metric | Value |", "|---|---:|",
             f"| Post-parser valid | {pct(summary['valid_post_parser_pct'])} |",
             f"| Strict raw JSON | {pct(summary['strict_raw_json_pct'])} |",
             f"| Tolerant recovery | {pct(summary['tolerant_recovery_pct'])} |",
             f"| Normalization | {pct(summary['normalization_pct'])} |",
             f"| Exceptions | {pct(summary['exception_pct'])} |",
             f"| > 500 ms | {pct(summary['exceeds_500ms_pct'])} |",
             f"| Decision latency p50 / p95 | {summary['decision_latency_ms']['p50']} / {summary['decision_latency_ms']['p95']} ms |",
             f"| Model latency p50 / p95 | {summary['model_latency_ms']['p50']} / {summary['model_latency_ms']['p95']} ms |",
             "", "## Action distribution", "", "| Command | Count |", "|---|---:|"]
    lines += [f"| {action} | {count} |" for action, count in summary["action_distribution"].items()]
    return "\n".join(lines) + "\n"

def comparison_report(value):
    benches = value["benchmarks"]
    lines = ["# Configuration comparison", ""]
    for bench in benches: lines += [f"## {bench['team'].replace('-', ' ').title()} {bench['role'].upper()}", "", benchmark_report(bench).split("\n", 2)[2]]
    for comp in value["comparisons"]:
        metric = comp["metrics"]
        lines += ["## Paired tactical differences", "", f"Matched decisions: {metric['matched_decisions']}", "",
                  f"Same action type: {pct(metric['same_action_type_pct'])}", "",
                  f"Different action type: {pct(metric['different_action_type_pct'])}", "",
                  "| Tactical rate | First configuration | Second configuration |", "|---|---:|---:|"]
        labels = (("pass_rate_pct", "Pass"), ("shoot_rate_pct", "Shoot"),
                  ("move_to_rate_pct", "Move"), ("press_ball_rate_pct", "Press"),
                  ("intercept_rate_pct", "Intercept"), ("aggressive_action_rate_pct", "Aggressive action"),
                  ("defensive_action_rate_pct", "Defensive action"))
        lines += [f"| {label} | {pct(metric['left'][key])} | {pct(metric['right'][key])} |"
                  for key, label in labels]
        lines += ["",
                  "Tactical mappings: aggressive = SHOOT, PRESS_BALL, SLIDE_TACKLE, INTERCEPT; defensive = MARK, FOLLOW_PLAYER, INTERCEPT, SLIDE_TACKLE, SET_STANCE."]
    return "\n".join(lines) + "\n"

parser = argparse.ArgumentParser(description="Produce a Markdown football-lab report from result JSON")
parser.add_argument("--benchmark", help="benchmark result JSON")
parser.add_argument("--comparison", help="comparison result JSON")
parser.add_argument("--output", help="write Markdown here (stdout when omitted)")
args = parser.parse_args()
if bool(args.benchmark) == bool(args.comparison): parser.error("provide exactly one of --benchmark or --comparison")
value = json.loads(Path(args.benchmark or args.comparison).read_text())
rendered = benchmark_report(value) if args.benchmark else comparison_report(value)
if args.output:
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(rendered)
else: print(rendered, end="")
