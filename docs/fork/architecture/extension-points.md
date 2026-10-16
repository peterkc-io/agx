---
title: Extension points
summary: >-
  The hooks, callbacks and loading paths that exist in the agx code today,
  who uses each one, and what does not exist yet. A starting map for plugin
  design, not a plugin API.
describes:
  agx: c79f02406
  upstream: 5f218f780
---

# Extension points

This page lists the places where the current code accepts behavior from
outside a component: typed callbacks, lists of tools, handler maps and resource
loaders. It is a map for the plugin work, not a plugin API. agx has no plugin
system yet. "Public" below means exported Rust API or a documented Python
function, not a stable contract for third-party code.

Today only two paths load code that is not compiled into `agx`:

- Python skills, which the kernel imports (see [Python kernel](kernel.md#skills-in-the-kernel));
- MCP servers, which the kernel's MCP client starts or connects to.

Everything else on this page is set in Rust when the engine is composed.

## Summary

| Surface                         | Kind                        | Set by today                     |
| ------------------------------- | --------------------------- | -------------------------------- |
| `AgentOptions` hooks            | Typed callbacks in the loop | `pa-core` `create_session`       |
| `StreamOptions` hooks           | Provider request, response  | Request timing                   |
| `Agent::subscribe`              | Ordered event listeners     | Persistence, telemetry, daemon   |
| Tool list (`AgentTool`)         | Construction-time list      | Engine adds `python_repl` only   |
| Host request handlers           | Named kernel-to-host calls  | `pa-core` runtime, MCP, daemon   |
| Skills, prompts, themes         | Resource loading            | Packages, settings, bundled      |
| MCP connections                 | Python MCP client           | Settings `mcpServers`, built-ins |
| `SessionEngineConfig` callbacks | Embedding seams             | Daemon worker, print mode        |
| Slash commands                  | Static builtin table        | Closed; no registration          |
| Settings                        | Typed configuration         | Each consumer reads its keys     |

## Agent loop hooks

`AgentOptions` (`crates/pa-agent/src/agent.rs`) has these optional callbacks:

- `convert_to_llm`, `transform_context`: change the messages sent to the model.
- `stream_fn`: the function that calls the model.
- `get_api_key`: supply a key per request.
- `before_tool_call`: see validated arguments and block a call; a blocked call
  becomes an error result.
- `after_tool_call`: replace fields of a tool result. Fields are replaced one by
  one, not merged deeply.
- `should_stop_after_turn`, `should_stop_before_turn`: end a run early.
- `get_continuation_messages`: add messages when the run would otherwise end.
  `Agent::set_continuation_hook` can replace it later.

The callback types are public in `pa_agent::agent_loop`. The lower-level
`AgentLoopConfig` also has `get_system_prompt`, `get_steering_messages` and
`get_follow_up_messages`; the `Agent` fills the last two from its own queues.

Today `create_session` (`crates/pa-core/src/session_engine/engine.rs`) sets the
stream function, message conversion, a timing pass-through transform, and the
stop hooks. It leaves `before_tool_call`, `after_tool_call` and `get_api_key`
unset. The side-question agent uses `before_tool_call` to block every tool and
`should_stop_after_turn` to limit its turns
(`crates/pa-core/src/session_engine/side_question.rs`). Daemon and print
autonomous modes install continuation hooks
(`crates/pa-daemon/src/autonomous_continuation.rs`,
`crates/pa-cli/src/print_autonomous.rs`).

## Provider hooks

`StreamOptions` (`crates/pa-ai/src/types.rs`) carries an `OnPayloadHook`, which
receives the request JSON and the model and may replace the JSON, and an
`OnResponseHook`, which sees the status and headers before the body is read. It
also carries cancellation, headers, transport, timeout, cache and service-tier
settings.

Request timing wraps these hooks and keeps any hook that was already set
(`instrument_stream_fn` in `crates/pa-core/src/session_engine/request_timing.rs`).
The provider adapter carries them from the loop to `pa-ai`
(`provider_adapter.rs`). The providers call the payload hook before they send
the request.

## Event subscription

`Agent::subscribe` adds an async listener for `AgentEvent` values: run and turn
boundaries, message start, delta and end, and tool start, update and end
(`crates/pa-agent/src/types.rs`). Session persistence, telemetry, image-route
cleanup and the daemon's turn forwarding all use it.

Listeners are part of the run, not background notifications:

- they run in subscription order, and the agent awaits each one;
- a listener error fails the run;
- a slow listener delays the run and its idle state;
- dropping the `Subscription` handle does not unsubscribe; call `unsubscribe`.

## Tools

There is no tool registry type. A session's tools are a
`Vec<Arc<dyn AgentTool>>` in `SessionEngineConfig.tools`. The engine appends
`python_repl` when the list does not have it. The daemon and print mode pass an
empty list, so the model sees only `python_repl`.

- `AgentTool` (`crates/pa-agent/src/types.rs`) defines name, description,
  schema, argument preparation, aliases, execution and execution mode.
- `ToolDefinition` (`crates/pa-core/src/tools/tool_definition.rs`) is the
  `pa-core` form; `ToolDefinitionBridge` adapts it to `AgentTool`.
- The unused `bash` and `edit` tools are still exported. `BashOperations` and
  `BashSpawnHook` can replace how bash runs, and `EditOperations` how edit
  writes; nothing sets them today.

## Kernel host request handlers

`HostRequestHandlers` (`crates/pa-core/src/kernel/shared.rs`) maps a request
type name to an async handler. `register` adds one; `merge` lets later entries
win. A host passes its own handlers in `SessionEngineConfig.extra_host_handlers`.
The engine merges them after its built-in handlers, then registers the MCP
handlers, so a later registration replaces an earlier one with the same name.
The daemon uses this seam for messaging, observation and subagents. From Python,
any `host_request` type reaches this map.

## Skills, prompts and packages

`PackageManager` (`crates/pa-core/src/packages/`) installs package sources (npm,
git or local) and resolves resource paths from user and project settings,
auto-discovery and bundled skills. It resolves three resource kinds only:
skills, prompt templates and themes. It does not load code modules.

`load_resources` (`crates/pa-core/src/resources/mod.rs`) loads the resolved
skills and prompt templates. Its options accept extra skill and prompt paths.
When two skills have the same name, the first one wins and a collision
diagnostic is recorded. A second skill at the same real path is skipped without a
diagnostic. Python skills become kernel packages; markdown skills become prompt
text.

## MCP

The host side, `McpManager` (`crates/pa-core/src/mcp/mod.rs`), reads the
`mcpServers` setting and the service catalog, handles login, and answers the
kernel's `mcp.config`, `mcp.refresh` and login calls. The protocol itself runs in
Python: `rlm.mcp` (`prime-agent-runtime/src/rlm/mcp.py`) connects over HTTP or
starts a stdio server process, and reconnects when the configuration changes.
MCP tools are not model tools. The model calls them from Python through the
generic MCP client.

## Embedding callbacks

`SessionEngineConfig` (`crates/pa-core/src/session_engine/engine.rs`) also
accepts hosts and callbacks for the program that embeds the engine: the RLM
subagent host, usage reporting, progress notes, background-work notices, an
external MCP manager, cron wiring, an image router and late agent messages.
`SessionManager::on_persist` (`crates/pa-core/src/session/manager/persist.rs`)
adds synchronous listeners that run after a session entry is written. These are
composition seams for the daemon and print mode, not a plugin lifecycle.

## What does not exist yet

- **No dynamic slash commands.** `SlashCommandRegistry`
  (`crates/pa-types/src/slash_commands.rs`) is built from a static table and has
  no register method. The CLI's top-level command table
  (`crates/pa-cli/src/command_registry.rs`) is crate-private. The `/plugins`
  command is an inherited service browser, not an agx plugin feature.
- **No tool registration from outside.** Tools come only from the list the host
  builds.
- **No extension settings.** `Settings` keeps unknown keys, but nothing reads an
  `extensions` key.
- **No live reload of every setting.** Some settings apply at once (queue modes,
  model, thinking level, and MCP and provider auth on `/reload`); others, such as
  the shell path, are read only when a session starts.

## Known gap

`ToolDefinitionBridge::execute`
(`crates/pa-core/src/session_engine/tool_bridge.rs`) copies a tool result's
content and details but does not pass on its `is_error` flag. A tool that reports
an error in its result, rather than returning `Err`, may not be marked as an
error in the loop. This was found by reading the source; it has not been tested.
