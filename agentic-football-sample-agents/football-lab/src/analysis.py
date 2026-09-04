"""Stable summary and tactical comparison calculations."""

from __future__ import annotations

import math
from collections import Counter, defaultdict

AGGRESSIVE_ACTIONS = frozenset({"SHOOT", "PRESS_BALL", "SLIDE_TACKLE", "INTERCEPT"})
DEFENSIVE_ACTIONS = frozenset({"MARK", "FOLLOW_PLAYER", "INTERCEPT", "SLIDE_TACKLE", "SET_STANCE"})


def percentile(values, percent):
    """Nearest-rank percentile (p50/p95), returning None for no observations."""
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    return values[max(0, math.ceil(percent / 100 * len(values)) - 1)]


def _rate(rows, predicate):
    return round(100 * sum(bool(predicate(row)) for row in rows) / len(rows), 3) if rows else 0.0


def summarize(rows):
    actions = Counter((row.get("action_type") or "OTHER") for row in rows)
    normalization = lambda row: any(row.get("parser_normalization", {}).values())
    summary = {"total_decisions": len(rows), "valid_post_parser_pct": _rate(rows, lambda r: r.get("post_parser_valid")),
               "strict_raw_json_pct": _rate(rows, lambda r: r.get("raw_strict_json")),
               "tolerant_recovery_pct": _rate(rows, lambda r: r.get("tolerant_recovery")),
               "normalization_pct": _rate(rows, normalization), "exception_pct": _rate(rows, lambda r: r.get("exception")),
               "exceeds_500ms_pct": _rate(rows, lambda r: r.get("exceeds_500ms")),
               "decision_latency_ms": {"p50": percentile([r.get("decision_latency_ms") for r in rows], 50),
                                       "p95": percentile([r.get("decision_latency_ms") for r in rows], 95)},
               "model_latency_ms": {"p50": percentile([r.get("model_latency_ms") for r in rows], 50),
                                    "p95": percentile([r.get("model_latency_ms") for r in rows], 95)},
               "action_distribution": dict(sorted(actions.items()))}
    groups = defaultdict(list)
    for row in rows:
        groups[(row.get("role"), row.get("scenario_metadata", {}).get("scenario_family"))].append(row)
    summary["breakdowns"] = {f"{role}:{family}": {"total": len(group),
        "valid_post_parser_pct": _rate(group, lambda r: r.get("post_parser_valid")),
        "action_distribution": dict(sorted(Counter(r.get("action_type") or "OTHER" for r in group).items()))}
        for (role, family), group in sorted(groups.items())}
    return summary


def compare_decisions(left, right):
    by_left = {(r["scenario_id"], r["run_index"]): r for r in left}
    by_right = {(r["scenario_id"], r["run_index"]): r for r in right}
    keys = sorted(by_left.keys() & by_right.keys())
    pairs = [(by_left[key], by_right[key]) for key in keys]
    same = _rate(pairs, lambda pair: pair[0].get("action_type") == pair[1].get("action_type"))
    def tactical(rows):
        return {f"{name.lower()}_rate_pct": _rate(rows, lambda row, name=name: row.get("action_type") == name)
                for name in ("PASS", "SHOOT", "MOVE_TO", "PRESS_BALL", "INTERCEPT")}
    return {"matched_decisions": len(pairs), "same_action_type_pct": same,
            "different_action_type_pct": round(100 - same, 3) if pairs else 0.0,
            "left": {**tactical([a for a, _ in pairs]),
                     "aggressive_action_rate_pct": _rate(pairs, lambda p: p[0].get("action_type") in AGGRESSIVE_ACTIONS),
                     "defensive_action_rate_pct": _rate(pairs, lambda p: p[0].get("action_type") in DEFENSIVE_ACTIONS)},
            "right": {**tactical([b for _, b in pairs]),
                      "aggressive_action_rate_pct": _rate(pairs, lambda p: p[1].get("action_type") in AGGRESSIVE_ACTIONS),
                      "defensive_action_rate_pct": _rate(pairs, lambda p: p[1].get("action_type") in DEFENSIVE_ACTIONS)}}

