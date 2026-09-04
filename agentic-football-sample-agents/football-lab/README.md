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

Exit status is zero only for a valid action without an exception. Decisions over 500 ms set
`exceeds_500ms` but are not themselves invalid. Total time includes scenario loading and module
initialization; model time covers only the Strands agent call. Invalid output is reported, never
repaired by lab validation. Note that the unchanged stock parser runs first and, by design, may
recover Python-style JSON, fill some target IDs, or clamp move coordinates; the lab flags tolerant
JSON recovery as malformed model output.

## Tests and offline behavior

```bash
python -m pytest tests
```

Tests load fixtures and exercise selection, strict reporting validation, malformed input/output,
timing, and serialization with the model boundary mocked. They do not require AWS credentials,
Bedrock access, Strands, or AgentCore. Merely inspecting/loading scenario JSON also works offline.
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
