---
title: A prompt turn
summary: >-
  What happens inside a session worker from the moment a prompt is picked up
  until the turn ends: prompt assembly, the agent loop, provider streaming,
  the python_repl tool, events, persistence, compaction and retries.
describes:
  agx: c79f02406
  upstream: 5f218f780
---

# A prompt turn

This page follows one prompt through a daemon session worker. It starts when the
worker picks the prompt off its queue and ends when the worker reports the turn
done. Socket routing before that point is on
[Processes and sessions](processes.md).

## Layers

Each layer calls the one below it. The arrows on the right show what comes back.

```text
pa-daemon  worker   TurnRunner::run_turn           queue pickup, persistence,
                         |                         client events, settlement
pa-daemon  engine   AgentSessionEngine::run_prompt  skill expansion, session commands
                    run_turns / run_model_turn      compaction checks, retry, failover
                         |
pa-core    session  AgentSession / SessionEngine    prompt assembly, admission,
                         |                          tools, harness digest
pa-agent   loop     Agent, run_agent_loop           stream -> tool calls -> repeat
                         |
pa-core    adapter  switchable_stream_fn            live provider target, cancellation
                         |
pa-ai      stream   stream_simple -> Provider       HTTP request, SSE parsing
                         |
                    model provider (network)        <- assistant message events
```

The split is deliberate. `pa-agent` owns the generic loop and tool dispatch,
but knows nothing about providers, concrete tools or sessions; it receives a
stream function and a list of `AgentTool` values. `pa-ai` knows nothing about
the loop. `pa-core` supplies the concrete tools and joins the two, and
`pa-daemon` drives the turn and owns its timing.

## 1. Pickup

`TurnRunner::run_turn` (`crates/pa-daemon/src/worker/turn.rs`) takes a batch of
queued items. It emits `agent_start` and `turn_start` and builds one
`PromptRequest` with the main text and images plus any rows delivered with them.
It runs the engine on Tokio's blocking pool (`spawn_blocking`) and starts a task
that flushes coalesced stream updates.

## 2. Admission

`AgentSessionEngine::run_prompt`
(`crates/pa-daemon/src/agent_engine/session_engine_impl.rs`) prepares the
prompt:

- expands `/skill:<name>` into a skill block, in the main message and in each
  batched row;
- runs a session command (`/compact`, `/refine`, `/goal`, `/autonomous`) locally
  instead of sending it to the model. A `/goal` start or resume can then start a
  model turn with its continuation message. Only the main message is checked
  for a session command. Batched rows are not checked: they reach the model as
  ordinary user messages, even when their text looks like a command;
- emits the accepted rows, then enters `run_turns`.

`run_turns` (`agent_engine/turn/run_loop.rs`) checks whether the context needs
compaction before the turn. `run_model_turn` (`agent_engine/turn/model.rs`)
resolves the model and checks its credentials.

The core session is built lazily on first use. The daemon gives `pa-core` an
in-memory session manager, because the worker owns the durable session file, and
an empty tool list (`crates/pa-daemon/src/agent_engine/lifecycle.rs`).

Inside `pa-core`, `AgentSession::prompt_with_images`
(`crates/pa-core/src/session_engine/admission.rs`) expands skills and prompt
templates, then checks the result for a session command again. A match returns
`PromptOutcome::SessionCommand` before the busy check. If a run is already
active, the prompt must be a steering or follow-up message; otherwise it is
refused. An idle session admits, in order, any pending harness digest, next-turn
rows, the user row and batched user rows. Batched rows get skill and template
expansion here, but no session-command check.

## 3. System prompt

`create_session` (`crates/pa-core/src/session_engine/engine.rs`) builds the
system prompt with `system_prompt_breakdown`
(`crates/pa-core/src/prompts/system_prompt.rs`). The prompt has a static prefix
that stays stable across sessions, so providers can cache it, followed by a
session-specific tail:

```text
static prefix  core -> usage rules -> opinionated guidelines -> model-specific extras
               (a custom system prompt replaces only this part)
dynamic tail   packages -> project context -> skills -> MCP servers
               -> environment -> session role -> appended guidance
```

The breakdown also returns the byte length of the static prefix. Model-specific
extras come from TOML rule maps, shipped and user-defined
(`crates/pa-core/src/prompts/model_prompts.rs`). Every matching rule applies; if
a map or file has an error, no extras are added and the session gets an error
row.

The harness digest, a summary of the session's continual harness state, is not
part of the system prompt. It is a hidden custom row that
becomes a separate user message at the provider boundary
(`crates/pa-core/src/session_engine/harness_digest.rs`).

The context sent to the model is not every line of the session file.
`build_session_context` (`crates/pa-core/src/session/mod.rs`) follows the
current branch from the root to the leaf and replaces everything before the
latest compaction with its summary and kept messages.

## 4. The agent loop

`Agent` (`crates/pa-agent/src/agent.rs`) allows one active run and rejects a
second. `run_agent_loop` (`crates/pa-agent/src/agent_loop/entry.rs`) emits the
opening events and repeats these steps:

1. Prepare the request: apply the optional `transform_context` hook, convert the
   messages for the model, and build tool schemas
   (`stream_assistant_response_inner` in `agent_loop/response.rs`).
2. Call the stream function and turn its events into `MessageStart`,
   `MessageUpdate` and `MessageEnd`.
3. If the assistant asked for tools, run them (see [Tools](#tools)) and append
   the results.
4. Emit `TurnEnd`. Check the stop hooks and steering messages, then loop back to
   step 1.
5. With no tool calls and no steering left, take follow-up messages first, then
   continuation messages from the continuation hook. When all are empty, emit
   `AgentEnd`.

If the assistant message is an error or an abort, the loop skips tools and ends
at once.

## 5. Provider streaming

The daemon's stream function is `switchable_stream_fn`
(`crates/pa-core/src/session_engine/provider_adapter.rs`). It reads the current
`ProviderTarget` on every call. This lets `/model` and provider failover switch
the target for later calls without rebuilding the session. It converts the
loop's types to `pa-types` and passes cancellation, credentials and hooks to
`pa_ai::stream_simple`. A separate task pumps provider events back into the
loop's vocabulary.

`stream_simple` (`crates/pa-ai/src/stream.rs`) picks the provider by the model's
API identifier (`model.api`), not its provider name. The registry has
implementations for Anthropic, OpenAI completions and responses, Azure
responses, Google and Vertex, Mistral, Bedrock and Codex responses
(`register_builtin_api_providers` in `crates/pa-ai/src/registry.rs`). Prime
Inference is configured on top of these APIs; it has no registry entry of its
own. `stream_simple` also limits the output budget against an estimate of the
input size.

A provider such as Anthropic runs its HTTP request in its own task. It applies
the payload hook, sends the request with cancellation and a timeout, calls the
response hook, checks the status, and parses server-sent events. Other providers
follow the same outline; this page traced only Anthropic in detail.

Models come from the live catalog in `pa-models` (`ModelCatalog::resolve` in
`crates/pa-models/src/chain.rs`), which falls back to a cached copy, then a
bundled copy, then a compiled list, without waiting for the network. `pa-core`'s
`ModelRegistry` adds overrides and custom models from `models.json`.

## Tools

The model has one tool: `python_repl`. The daemon passes no tools, and
`create_session` adds the kernel-backed `python_repl` tool when the list does
not have one (`crates/pa-core/src/session_engine/engine.rs`). Print mode also
passes an empty list (`builtin_tools` in `crates/pa-cli/src/print_runtime.rs`).

`pa-core` still contains `bash` and `edit` tool implementations
(`crates/pa-core/src/tools/bash.rs`, `edit.rs`), but no shipped mode registers
them. Shell commands run through the `bash()` helper inside the Python kernel.
`rename` is a kernel host request (`rlm.rename`), and stdout is a kernel
protocol event; neither is a model tool.

How a tool call runs (`crates/pa-agent/src/agent_loop/tools.rs`,
`tool_call.rs`):

1. Find the tool by exact name, then by alias. An unknown tool becomes an error
   result.
2. Prepare and validate the arguments against the tool's JSON schema. Invalid
   arguments become an error result.
3. Run the `before_tool_call` hook, which can block the call.
4. Execute with abort and update callbacks. `ToolDefinitionBridge`
   (`crates/pa-core/src/session_engine/tool_bridge.rs`) maps the loop's abort to
   a cancellation token and streams updates back.
5. Run the `after_tool_call` hook, which can replace parts of the result.

Tools run one at a time when the session is set to sequential or when any
requested tool requires it; otherwise they run in parallel. `python_repl` is
marked sequential. Tool end events arrive in completion order, but result
messages go back to the model in the assistant's order.

`python_repl` streams startup notes and cell output as tool updates. Its final
result holds text and images, with status, stdout, stderr, result and error in
the details. [Python kernel](kernel.md) covers what happens on the other side.

## 6. Events and persistence

`run_turn_once` (`agent_engine/turn/run_once.rs`) subscribes to agent events
and maps them to `EngineEvent` values on an unbounded channel. The worker then:

- writes settled rows to the session file: user, assistant and tool result
  messages, custom rows, compaction entries and goal changes;
- sends session events to clients: `message_start/update/end`,
  `tool_execution_start/update/end`, `turn_start/end`, `agent_start/end`, and
  compaction, goal, refinement and retry events.

Streaming deltas are coalesced for 50 ms (`UPDATE_FLUSH_INTERVAL` in
`crates/pa-daemon/src/streaming.rs`). A block end or other direct frame flushes
the pending deltas first, so terminal frames are never delayed. Deltas are not
written to the session file; only settled messages are.

**Abort.** `abort_in_flight_turn` calls the agent's `abort()` at once. Closing or
dropping the model stream cancels the HTTP request. The loop builds an aborted
assistant message from any partial content.

**Settlement.** After the run, the engine drains the remaining events. The outer
`run_turns` runs any scheduled boundary work, checks compaction again, handles
goal continuation, and emits exactly one `Done`. The worker then clears its busy
state and pushes a roster update.

## 7. Compaction and retries

- **Retry and failover.** `run_model_turn` wraps model attempts. A retry removes
  the failed assistant message and continues the run; it does not add the user
  message again. If a provider runs out of quick retries and another provider
  serves the same model, the turn moves to the next one. The decision logic is in
  `crates/pa-core/src/session_engine/provider_retry.rs` and
  `provider_failover.rs`; the daemon owns the waits and the switch.
- **Threshold compaction.** `run_turns` checks before and after the run. During a
  long run with many tools, a stop hook ends the run early when context headroom
  runs out. `run_auto_compaction` (`crates/pa-daemon/src/auto_compaction.rs`)
  emits `compaction_start`, calls `AgentSession::compact`, and reports the
  outcome.
- **Overflow recovery.** When the provider reports a context overflow for the
  current model, the daemon compacts and retries once
  (`crates/pa-daemon/src/overflow_compaction.rs`). A second overflow is
  reported, not retried.
- **What compaction changes.** `AgentSession::compact`
  (`crates/pa-core/src/session_engine/compaction_arms.rs`) replaces the live
  context with a summary plus kept messages. It does not rewrite session history,
  and it does not reset the kernel; a running kernel gets an `ipython_state`
  notice instead.
- **Auto-refine** after compaction waits until the worker is idle, so a queued
  prompt does not wait behind it.
- **From the kernel.** `compact.run()` and `refine.run()` in Python only schedule
  this work; it runs at the next turn boundary, never inside the calling cell.

## Telemetry

The engine still has its upstream telemetry points: agent start, run completed,
retries, compaction, skill use and session end
(`crates/pa-core/src/session_engine/telemetry.rs`). In agx, release builds force
recording off, and `telemetry_endpoint()` returns `None` in every build
(`crates/pa-core/src/session_engine/telemetry/status.rs`). So these points send
nothing over the network.

## Code map

- `crates/pa-daemon/src/worker/turn.rs`: pickup, persistence, client events,
  settlement.
- `crates/pa-daemon/src/agent_engine/`: admission, turn loop, retry, session
  construction.
- `crates/pa-core/src/session_engine/`: session composition, admission, tool
  bridge, provider adapter, compaction, harness digest.
- `crates/pa-core/src/prompts/`: system prompt layers and model prompt rules.
- `crates/pa-agent/src/`: agent run lifecycle and loop.
- `crates/pa-ai/src/`: streaming facade, provider registry, providers.
- `crates/pa-models/src/`, `crates/pa-core/src/models/`: model catalog and local
  overrides.
