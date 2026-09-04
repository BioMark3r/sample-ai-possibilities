# Local testing architecture

This document records what is present in the repository; it does not describe a replacement
agent design.

## Teams and roles

Five public teams are present: `ai-team-strands-balanced` (the default/reference team),
`ai-team-strands-extremely-aggressive`, `ai-team-strands-extremely-defensive`,
`ai-team-strands-gateway`, and `ai-team-strands-memory`. The last two add AgentCore Gateway MCP
tools and AgentCore Memory respectively. Every team has `ai-gk`, `ai-def`, `ai-mid`, `ai-fwd1`,
and `ai-fwd2` directories. The balanced role modules define these fixed identities:

| Role | Player | Entry point | Model |
|---|---:|---|---|
| GK | 0 | `ai-team-strands-balanced/ai-gk/src/main.py` | `us.amazon.nova-micro-v1:0` |
| DEF | 1 | `ai-team-strands-balanced/ai-def/src/main.py` | `us.amazon.nova-lite-v1:0` |
| MID | 2 | `ai-team-strands-balanced/ai-mid/src/main.py` | `us.amazon.nova-pro-v1:0` |
| FWD1 | 3 | `ai-team-strands-balanced/ai-fwd1/src/main.py` | `us.amazon.nova-micro-v1:0` |
| FWD2 | 4 | `ai-team-strands-balanced/ai-fwd2/src/main.py` | `us.amazon.nova-lite-v1:0` |

Each `main.py` owns only its `SYSTEM_PROMPT`, `MY_PLAYER_ID`, `POSITION_LABEL`, selected model,
and fallback configuration. It creates `app = BedrockAgentCoreApp()`, `agent = create_agent(...)`,
registers the shared handler with `create_invoke_handler(...)`, and runs `app.run()` only under the
main guard. Thus `src/main.py` is both the deploy/runtime entry point and the source of the locally
callable Strands `agent` object.

## Shared path and wire contract

The shared implementation is `lib/`: `agent_base.create_agent` constructs a Strands `Agent` around
`strands.models.BedrockModel`; `agent_base.create_invoke_handler` supplies the AgentCore entrypoint;
`state.summarize_state` converts a state to the model prompt; `parsing.parse_commands` extracts and
tags model commands; and `fallback.build_fallback` provides position-specific rule behavior.

`create_invoke_handler.invoke(payload, context)` accepts an AgentCore payload whose `prompt` is
either a JSON string or object. That prompt contains `gameState`, numeric `teamId`, and optional
`myPlayers`. `gameState` uses `ball`, `players`, `score`, `gameTime`, and `playMode`. The state helper
explicitly supports current `agentId`/`teamCode`/`possessionAgentId` fields and legacy
`playerId`/`teamId`/`possessionPlayerId` fields. The fixtures in `lib.test_helpers.GAME_STATE` are the
repository's concrete current-schema example and are the basis of the lab fixtures.

The handler calls the model synchronously, passes its string result through
`parsing.parse_commands`, and yields a JSON-encoded **array** of commands. `parsing.VALID_COMMANDS`
is the authoritative command-type list. Prompts in each role module document parameters for
`MOVE_TO`, `PASS`, `SHOOT`, `SLIDE_TACKLE`, `PRESS_BALL`, `INTERCEPT`, `MARK`, `FOLLOW_PLAYER`,
`GK_DISTRIBUTE`, `SET_STANCE`, `CLEAR_OVERRIDE`, and `RESET`. The parser overwrites `teamId` and
`playerId`, filters unknown types, clamps `MOVE_TO`, and fills certain missing targets. These are
stock behaviors; the lab does not alter them.

## Local invocation and dependencies

**Yes: the balanced stock agents can make decisions locally without an AgentCore deployment.**
The existing `test_local.py` files already directly call `agent(summary)` in their opt-in `--llm`
test. `BedrockAgentCoreApp` is transport/deployment glue, not a prerequisite for the Strands model
call. The lab's thin adapter imports the unchanged role module, substitutes only the decorator
surface of `BedrockAgentCoreApp`, then calls its existing `agent`, `summarize_state`, and
`parse_commands`. No Event Code or Kiro flow is involved.

A live decision still requires Python 3.10+, `strands-agents`, AWS credentials recognized by the
AWS SDK, a configured AWS region (for example `AWS_DEFAULT_REGION=us-east-1`), and permission/model
access for the relevant Amazon Nova inference profile through Amazon Bedrock Runtime. AgentCore
credentials, a deployed runtime, Node/CDK, Gateway, and Memory are not required for the balanced
lab path. Offline lab unit tests need none of those AWS resources and mock the adapter boundary.

Model-call latency is naturally exposed around `module.agent(prompt)` and recorded separately.
The stock handler's fallback-on-error path is not invoked by this adapter: surfacing an exception
is intentional for a decision-testing lab. Successful model output still uses the exact stock
parser (including its documented tolerant JSON recovery), and the result reports when recovery or
parsing failure made the raw model output malformed.

Current Phase 1 scope is deliberately balanced-team only. Gateway and Memory teams require
additional live service/session setup, so they are documented but not exposed as misleading local
choices. No repository blocker was found for balanced direct invocation; a live call cannot be
verified without AWS credentials and Bedrock model access.
