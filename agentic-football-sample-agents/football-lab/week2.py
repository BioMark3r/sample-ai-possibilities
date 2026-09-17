#!/usr/bin/env python3
"""Offline-first Week 2 official-match observation workflow."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from week2 import Week2Store, candidate_config, markdown_report, report_data, trends

def _json(value):
    if value == "-": return json.load(sys.stdin)
    return json.loads(Path(value).read_text(encoding="utf-8"))

def main(argv=None):
    p=argparse.ArgumentParser(description="Offline Week 2 match analysis and regression capture")
    p.add_argument("--workspace", default="week2", help="offline workspace directory")
    sub=p.add_subparsers(dest="command", required=True)
    n=sub.add_parser("new-match"); n.add_argument("--match", required=True); n.add_argument("--official-match-id"); n.add_argument("--opponent"); n.add_argument("--final-score"); n.add_argument("--date-time"); n.add_argument("--notes"); n.add_argument("--configuration"); n.add_argument("--git-sha")
    o=sub.add_parser("observe"); o.add_argument("--match", required=True); o.add_argument("--role"); o.add_argument("--problem", required=True); o.add_argument("--severity", default="medium"); o.add_argument("--notes"); o.add_argument("--payload", help="JSON path, or - for stdin"); o.add_argument("--controlled-player-id", type=int); o.add_argument("--game-time", type=float); o.add_argument("--score"); o.add_argument("--observed-action"); o.add_argument("--expected-behavior"); o.add_argument("--tag", action="append", dest="tags")
    x=sub.add_parser("promote"); x.add_argument("--observation", required=True)
    r=sub.add_parser("report"); r.add_argument("--match", required=True); r.add_argument("--json", action="store_true", dest="as_json")
    c=sub.add_parser("suggest-config"); c.add_argument("--match", required=True); c.add_argument("--problem", required=True); c.add_argument("--output")
    sub.add_parser("trends")
    a=p.parse_args(argv); store=Week2Store(a.workspace)
    try:
        if a.command=="new-match": out=store.new_match(a.match, official_match_id=a.official_match_id, opponent=a.opponent, final_score=a.final_score, date_time=a.date_time, notes=a.notes, configuration=a.configuration, git_sha=a.git_sha)
        elif a.command=="observe": out=store.observe(a.match, a.role, a.problem, a.severity, _json(a.payload) if a.payload else None, notes=a.notes, controlled_player_id=a.controlled_player_id, game_time=a.game_time, score=_json(a.score) if a.score else None, observed_action=_json(a.observed_action) if a.observed_action else None, expected_behavior=a.expected_behavior, tags=a.tags)
        elif a.command=="promote": out=store.promote(a.observation)
        elif a.command=="report":
            out=report_data(store,a.match)
            if not a.as_json:
                text=markdown_report(out); path=store.root/"reports"/f"{a.match}.md"; path.write_text(text,encoding="utf-8"); print(text); return out
        elif a.command=="suggest-config":
            out=candidate_config(store,a.match,a.problem)
            if a.output: Path(a.output).write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
        else: out=trends(store)
        print(json.dumps(out,indent=2,sort_keys=True)); return out
    except (ValueError, OSError, json.JSONDecodeError) as e: p.error(str(e))

if __name__=="__main__": main()
