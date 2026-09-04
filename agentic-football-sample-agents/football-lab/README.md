# Agentic Football decision-testing lab

This Phase 1 lab runs a saved current-schema `gameState` through an unchanged balanced sample
agent and reports the parsed command, validity, exceptions, and latency. It is intentionally
separate from every agent and deployment directory.

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
API only avoids repeated Python/module/model initialization and does not implement batch
benchmarking or game progression. The role module's `MY_PLAYER_ID` is always authoritative, so the
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

- Only the reference `balanced` team is enabled in Phase 1. Gateway and Memory variants have extra
  service dependencies and are not silently degraded.
- This is one invocation, not physics, game progression, team-vs-team simulation, or benchmarking.
- Timeouts are reported when the underlying AWS/model SDK raises one. The harness measures elapsed
  time but does not terminate an in-flight SDK call; configure botocore/model timeouts externally.
- The adapter follows the stock handler's successful model path but deliberately reports model
  exceptions rather than activating rule-based fallbacks, making failures visible to experiments.
