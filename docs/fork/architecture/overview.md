---
title: Overview
summary: >-
  Bird's-eye view of agx: the processes that run, the crates and their
  dependencies, entry points, architecture rules, and where upstream docs
  differ from the code.
describes:
  agx: c79f02406
  upstream: 5f218f780
---

# Overview

agx is a fork of Prime Agent, a coding agent written in Rust. It keeps the
upstream engine, wire protocol and on-disk session format. The fork adds its own
executable name and process namespace, a settings overlay, and switches off
updates, usage telemetry and trace uploads. A plugin system is planned but not
built. The [fork overlay](fork-overlay.md) page covers the fork changes.

## Bird's-eye view

In the normal interactive case, three kinds of process cooperate, plus one
Python kernel per active session:

```text
  terminal                          background
 +-------------------+  JSONL      +---------------------------------+
 | agx  (client)     |------------>| agx --mode daemon  (supervisor) |
 | pa-cli + pa-tui   |  socket     | registry, routing, restarts     |
 +-------------------+             +---------------------------------+
        |                                  | starts "agx worker",
        | direct link                      | one per active session
        | (private frames)                 v
        |                          +---------------------------------+
        +------------------------->| session worker                  |
                                   | pa-daemon worker + pa-core      |
                                   | engine + pa-agent loop          |
                                   +---------------------------------+
                                      | stdin/stdout JSONL    | HTTPS
                                      v                       v
                            +--------------------+    model providers
                            | python -m rlm.repl |    (pa-ai)
                            | kernel, 1/session  |
                            +--------------------+
```

1. You run `agx` in a terminal. The CLI checks for a running supervisor on the
   agx socket and starts one in the background if needed.
2. The supervisor starts a separate `agx worker` process for each active
   session. Sessions do not share a process, so one crashing session does not
   take down the others or the UI.
3. The terminal UI talks to the supervisor over a JSONL socket. For an attached
   session it upgrades to a direct link to that session's worker.
4. The worker runs the session engine. It streams model output from the
   provider and runs tools.
5. The model has one tool, `python_repl`. It runs code in a persistent Python
   process that the worker starts on first use or ahead of time. Shell
   commands, MCP calls and subagents (`rlm.spawn`) are Python functions inside
   that kernel.

The daemon keeps session history on disk as JSONL files. This lets it recover
a session after a worker crash, a supervisor restart or a UI restart.
[Processes and sessions](processes.md) explains the supervisor, the workers and
the recovery paths.

## Run modes

`pa-cli` picks the mode in `AppMode::resolve` (`crates/pa-cli/src/mode.rs`).
An explicit `--mode` wins. Otherwise `--print` or non-terminal stdin selects
print mode, and a terminal selects interactive mode.

| Mode                             | Where the session engine runs | Talks over                   |
| -------------------------------- | ----------------------------- | ---------------------------- |
| Interactive (terminal stdin)     | Daemon session worker         | Terminal UI (`pa-tui`)       |
| Print (`--print` or piped stdin) | Inside the `agx` process      | Text on stdout, exit code    |
| `--mode json`                    | Inside the `agx` process      | JSON events on stdout        |
| `--mode rpc`                     | Inside the `agx` process      | JSON lines on stdin/stdout   |
| `--mode acp`                     | Daemon session worker         | ACP JSON-RPC on stdin/stdout |
| `--mode daemon`                  | None; this is the supervisor  | JSONL socket                 |
| `worker` (internal)              | This process is the worker    | Socket, private frames       |

Print, JSON and RPC modes run without a supervisor. In print mode, subagents
run as in-process session nodes and end with the process. In daemon-backed
modes, each subagent is its own supervised worker.

## Crates

The workspace has 11 crates. Nine come from upstream (`pa-*`); two are fork
crates (`agx-*`). Each crate's `README.md` lists its scope and public API.

| Crate          | Owns                                                               |
| -------------- | ------------------------------------------------------------------ |
| `pa-types`     | Shared wire and domain types, daemon framing, platform transport   |
| `pa-telemetry` | Telemetry events, queue and sinks                                  |
| `pa-agent`     | Provider-independent agent loop                                    |
| `pa-ai`        | Provider clients, streaming, provider registry                     |
| `pa-models`    | Live model catalog with offline fallbacks                          |
| `pa-core`      | Session engine, tools, kernel, prompts, skills, settings, MCP host |
| `pa-daemon`    | Supervisor, session workers, wire protocol, ACP and RPC            |
| `pa-tui`       | Terminal UI and daemon client                                      |
| `pa-cli`       | The `agx` binary; composition root                                 |
| `agx-identity` | Fork process isolation, upstream socket refusal, policy constants  |
| `agx-settings` | RFC 7396 merge-patch operations for the settings overlay           |

Direct workspace dependencies, from the `Cargo.toml` files (`*` marks a fork
edge):

```text
pa-cli     -> pa-daemon, pa-tui, pa-core, pa-ai, pa-agent, pa-telemetry, pa-types
pa-daemon  -> pa-core, pa-ai, pa-agent, pa-telemetry, pa-types  (tests: pa-models)
pa-tui     -> pa-types
pa-core    -> pa-models, pa-ai, pa-agent, pa-telemetry, pa-types, agx-settings*
pa-models  -> pa-ai, pa-types
pa-ai      -> pa-types
pa-types   -> agx-identity*
pa-agent, pa-telemetry, agx-identity, agx-settings -> no workspace crates
```

Dependencies point from higher crates to lower ones, with no cycles. `pa-tui`
depends on `pa-types` alone, so the UI never links the session engine. It only
sends commands and renders events.

`pa-core`'s dependency on `agx-settings` has one unusual detail. The pure JSON
functions come from the crate. The overlay's host adapter,
`crates/agx-settings/src/manager.rs`, is compiled inside `pa-core` through a
`#[path]` module in `crates/pa-core/src/settings/manager.rs`. This lets the
adapter use `pa-core` internals without a reverse dependency.

The repository also holds two non-Rust parts:

- `prime-agent-runtime/`: the Python package `rlm` that runs as the kernel. See
  [Python kernel](kernel.md).
- `skills/`: the bundled skills, both markdown and Python, that ship beside the
  binary.

## Entry points

| Where to start                                 | What it is                                   |
| ---------------------------------------------- | -------------------------------------------- |
| `crates/pa-cli/src/main.rs`                    | `agx` `main`: fork startup, then dispatch    |
| `crates/pa-cli/src/mode.rs`                    | `AppMode::resolve`, mode selection           |
| `crates/pa-cli/src/print_runtime.rs`           | `PrintRuntime`: dispatch to every mode       |
| `crates/pa-cli/src/interactive_mode/daemon.rs` | Supervisor probe and detached start          |
| `crates/pa-daemon/src/supervisor.rs`           | `Supervisor`: the background daemon          |
| `crates/pa-daemon/src/worker.rs`               | `run_worker`: a session worker               |
| `crates/pa-daemon/src/worker/turn.rs`          | `TurnRunner::run_turn`: one prompt turn      |
| `crates/pa-core/src/session_engine/engine.rs`  | `create_session`: builds the session runtime |
| `crates/pa-agent/src/agent_loop/`              | The agent loop                               |
| `prime-agent-runtime/src/rlm/repl.py`          | The Python kernel's `main`                   |

The workspace declares two more binaries: `pa-daemon` (its own `main` in
`crates/pa-daemon/src/main.rs`) and `pa-tui-replay`. The shipped executable is
`agx`. The supervisor and the workers are the same `agx` executable, started
with `--mode daemon` and `worker`.

## Architecture rules

These rules are deliberate. Some are written in `AGENTS.md`; others follow from
the code.

- **One owned area per crate.** `pa-types` is the only shared vocabulary crate.
  Wire types that both the daemon and the UI need live there.
- **The UI does not link the engine.** `pa-tui` depends only on `pa-types`. It
  renders daemon events and sends user intents as daemon commands.
- **`pa-cli` is the composition root.** It wires crates together and starts
  processes. `AGENTS.md` says it holds no business logic, but it does own the
  CLI's own commands, such as login flows, daemon discovery and the update
  refusal.
- **One worker process per active session.** The supervisor holds registry and
  routing state, not session engines.
- **One run at a time per session.** The agent rejects a second concurrent run.
  A prompt that arrives during a run is queued as a steering or follow-up
  message.
- **Only settled messages become history.** Streaming deltas go to clients but
  are not written to the session file.
- **The fork shares sessions and base settings with upstream, but not
  processes.** agx uses its own socket names and kernel venv, and refuses upstream
  sockets before it connects or binds.
- **Nothing on the paint path waits for the network.** `AGENTS.md` states this
  rule for first paint and every frame. In agx, product telemetry has no
  endpoint at all.

## Where upstream docs differ from the code

The upstream `AGENTS.md` and crate READMEs are upstream files. agx leaves them as
upstream wrote them, which keeps upstream syncs simple. They differ from the code at `c79f02406` in
these places. Trust the code.

- **Model tools.** `AGENTS.md` lists `bash`, `edit` and `python_repl` as model
  tools. The daemon and print mode register only `python_repl`; the `bash` and
  `edit` tool code in `pa-core` exists but is not registered. See
  [A prompt turn](prompt-turn.md#tools).
- **Crate dependencies.** The `AGENTS.md` crate table omits both fork crates
  and their edges, and lists `pa-daemon -> pa-models` without saying it is
  test-only. The READMEs of `pa-types`, `pa-core`, `pa-daemon` and `pa-cli`
  list fewer dependencies than their `Cargo.toml` files. The list
  [above](#crates) is current.
- **Stale names.** The `pa-core` README names a `ToolRegistry`, and the
  `pa-agent` README names `run_loop` and a `ToolDispatcher` trait. The current
  code has none of these as public API: tools are a list of `AgentTool` values,
  and the public loop entry points are `run_agent_loop` and
  `run_agent_loop_continue`.
- **IPython.** The `pa-core` README and some type names say IPython. The kernel
  is plain CPython with asyncio; it does not use IPython.
- **Executable name and updates.** The `pa-cli` README describes a
  `prime-agent` binary with a working update flow. In agx the binary is `agx`,
  and update commands refuse with local install instructions.
- **Append-only history.** `AGENTS.md` calls session files append-only. Normal
  writes append, but explicit rewrite and repair operations exist.
- **Placeholder text.** `crates/pa-cli/src/mode.rs` still describes an
  `UnavailableRuntime`; `main` uses `PrintRuntime`.
