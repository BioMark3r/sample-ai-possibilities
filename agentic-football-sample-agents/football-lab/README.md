# Agentic Football local benchmarking lab

The lab runs independent, deterministic decision states through unchanged stock agents. Phase 2
adds corpus generation, repeatable benchmarking, SQLite experiments, paired tactical comparison,
and Markdown reports while preserving the Phase 1 single-scenario API. It deliberately does not
implement game physics, ticks, matches, prompt optimization, or deployment.

The architecture is intentionally one-way:

```text
scenario generation -> immutable JSONL corpus -> LocalAgent -> decision result
                    -> experiment store -> analysis/reporting
```

## Setup

Python 3.10 or newer is required. From this directory, create an environment and install the same
runtime packages declared by a balanced agent:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

For a **live run**, configure AWS SDK credentials (environment variables, AWS profile, or another
standard credential provider), set a region, and ensure the account/role can invoke the selected
Amazon Nova model through Amazon Bedrock Runtime. MID uses `us.amazon.nova-pro-v1:0`; other role
model mappings are in `../LOCAL_TESTING.md`. No Event Code, Kiro workshop, AgentCore deployment,
CDK, Gateway, or Memory resource is needed.

## Run

From `football-lab/`:

```bash
AWS_DEFAULT_REGION=us-east-1 python run_scenario.py \
  --team balanced \
  --agent mid \
  --scenario scenarios/basic_possession.json
```

Add `--json` for machine-readable output. Available agents are `gk`, `def`, `mid`, `fwd1`, and
`fwd2`. The three small fixtures cover midfielder possession, a defender under pressure, and a
forward shooting opportunity. Their envelope is the stock handler's inner prompt object:
`teamId`, `myPlayers`, and `gameState`.

Exit status is zero only for a post-parser valid action without an exception. Results separate:

- `total_latency_ms`: the entire CLI-style run, including scenario loading and cold initialization;
- `cold_start_ms`: loading and initializing the selected stock module;
- `decision_latency_ms`: warm prompt summarization, model call, and stock parsing;
- `model_latency_ms`, `parsing_latency_ms`, and `validation_latency_ms`: measured components.

The `exceeds_500ms` decision-budget flag uses **only** `decision_latency_ms`; it does not make an
otherwise valid action invalid. These local wall-clock figures are diagnostic and are not claims
about production AgentCore latency.

Raw compliance is reported separately through `raw_strict_json`, `raw_expected_structure`, and
`tolerant_recovery`. `post_parser_valid` says whether the resulting command passes lab validation
(`valid_action` remains as a compatibility alias). `parser_normalization` exposes observable player
or team ID changes, supplied targets, coordinate clamping, and filtered unknown commands. The
unchanged stock parser remains authoritative and may recover Python-style JSON, supply some target
IDs, or clamp move coordinates; lab validation does not perform additional repairs.

Stock teams available locally are `balanced`, `extremely-aggressive`, and `extremely-defensive`.
Gateway and Memory remain excluded because they need additional services.

## Generate and benchmark

Every JSONL row has separate `metadata` and `payload` objects. The payload remains directly
compatible with `LocalAgent`; metadata records the ID, family, seed, role, player, possession,
ball zone, score state, time bucket, and pressure. Supported families are `possession`,
`transition_attack`, `transition_defense`, `under_pressure`, `shooting_opportunity`, `loose_ball`,
and `defensive_shape`. `transition` selects both transition families and `all` cycles all families.

```bash
python generate_scenarios.py --role mid --scenario-set transition --count 100 --seed 42 \
  --output generated/transition-mid-seed42.jsonl
python benchmark.py --team balanced --agent mid \
  --scenarios generated/transition-mid-seed42.jsonl --runs 1 \
  --output results/balanced-mid-transition.json
python compare.py --scenario-set generated/transition-mid-seed42.jsonl \
  --config balanced:mid --config extremely-aggressive:mid \
  --output results/transition-comparison.json
python report.py --comparison results/transition-comparison.json \
  --output results/transition-comparison.md
```

All commands provide `--help`. `benchmark.py` and `compare.py` default to
`results/football_lab.sqlite`, create it automatically, and print structured JSON. A benchmark
uses exactly one warm `LocalAgent` per team/role and `--runs N` repeats every state N times.
Comparison loads the corpus once and passes the same unchanged in-memory rows to each configuration.

### First balanced-vs-aggressive MID experiment

From `football-lab/`, run exactly:

```bash
python generate_scenarios.py --role mid --scenario-set all --count 500 --seed 42 \
  --output generated/all-mid-seed42.jsonl
python compare.py --scenario-set generated/all-mid-seed42.jsonl \
  --config balanced:mid --config extremely-aggressive:mid --runs 1 \
  --database results/football_lab.sqlite --output results/balanced-v-aggressive-mid.json
python report.py --comparison results/balanced-v-aggressive-mid.json \
  --output results/balanced-v-aggressive-mid.md
```

The database contains `benchmarks` (configuration, corpus digest, creation time), `scenarios`
(metadata and exact payload JSON), and `decisions` (one stable result JSON per scenario/run).
Initialization and migrations use `CREATE TABLE IF NOT EXISTS`; no manual setup is required.

Summaries report decision count; post-parser validity, strict JSON, tolerant recovery,
normalization, exception, and >500 ms percentages; decision/model p50 and p95; action distribution;
and role/family breakdowns. Paired comparisons report same/different command percentages plus pass,
shoot, move, press, intercept, aggressive, and defensive rates. The explicit aggressive mapping is
`SHOOT`, `PRESS_BALL`, `SLIDE_TACKLE`, `INTERCEPT`; the defensive mapping is `MARK`,
`FOLLOW_PLAYER`, `INTERCEPT`, `SLIDE_TACKLE`, `SET_STANCE`. These describe behavior, not quality.

## Reuse a warm agent

Add the lab's flat `src` directory to `PYTHONPATH`, then initialize once when callers need multiple
independent decisions:

```bash
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
```

```python
from runner import LocalAgent

agent = LocalAgent("balanced", "mid")
result1 = agent.run("scenarios/basic_possession.json")
result2 = agent.run("scenarios/forward_shooting_opportunity.json")
```

`LocalAgent.run` also accepts an already-loaded scenario dictionary. Each call is independent; this
API avoids repeated Python/module/model initialization and does not implement game progression. The role module's `MY_PLAYER_ID` is always authoritative, so the
ordering or contents of a fixture's realistic `myPlayers` field cannot change the controlled role.

## Tests and offline behavior

```bash
python -m pytest tests
```

Tests load fixtures and exercise selection, strict reporting validation, malformed input/output,
cold/warm timing, raw compliance, parser normalization, and serialization with the model boundary
mocked. They do not require AWS credentials, Bedrock access, Strands, or AgentCore. Merely inspecting/loading scenario JSON also works offline.
Actual agent selection/import and decision calls require `strands-agents`; actual decisions require
AWS credentials and Bedrock model access.

## Known limitations

- Gateway and Memory variants have extra service dependencies and are not silently degraded.
- Scenarios are independent synthetic decision probes, not realistic physics or progression.
- Timeouts are reported when the underlying AWS/model SDK raises one. The harness measures elapsed
  time but does not terminate an in-flight SDK call; configure botocore/model timeouts externally.
- The adapter follows the stock handler's successful model path but deliberately reports model
  exceptions rather than activating rule-based fallbacks, making failures visible to experiments.
