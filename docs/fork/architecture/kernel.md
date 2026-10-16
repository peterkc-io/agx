---
title: Python kernel
summary: >-
  How the Rust session engine starts, talks to and supervises the persistent
  Python kernel; what the rlm runtime package owns; how kernel calls reach
  Rust; and how the kernel venv and skills are prepared.
describes:
  agx: c79f02406
  upstream: 5f218f780
---

# Python kernel

The model's only tool, `python_repl`, runs code in a persistent Python process.
Each session has its own kernel. Rust owns the process: it starts the kernel,
sends it cells, collects output, answers its calls back into the host, and shuts
it down. Python owns cell execution and the helpers the model uses inside cells,
such as `bash()`, `rlm.spawn()` and MCP clients.

The kernel is plain CPython with asyncio, in the `rlm` package under
`prime-agent-runtime/src/rlm/`. It does not use IPython, although several Rust
names still say `Ipython`.

## The boundary

```text
 session worker (Rust, pa-core)                    kernel (python -m rlm.repl)
 ------------------------------                    ---------------------------
 python_repl tool                                  __main__ namespace (persistent)
   -> IpythonKernelProvisioner (1 per session)     asyncio event loop
   -> ReplKernelManager                            reader thread on stdin
        execute  --------- stdin, JSONL ---------> execute cell, top-level await
        host_reply --------------------------->    resolve awaiting call
        <-------- private stdout dup, JSONL ------ stdout/stderr, result, error, done
        <------------------------------------------ host_request (rlm.*, mcp.*, ...)
   HostRequestHandlers -> RLM host, MCP manager, goal, compact, messaging ...
```

The wire is newline-delimited JSON, protocol version 3. Rust checks the version
in the kernel's `ready` event and refuses a mismatch
(`crates/pa-core/src/kernel/manager/startup.rs`). The full message reference is
`prime-agent-runtime/src/rlm/repl.md`; the Rust parser is
`crates/pa-core/src/kernel/protocol.rs`.

Protocol frames leave the kernel on a private duplicate of the original stdout,
made before user code runs. Cell output cannot break framing:

- Python-level writes to `sys.stdout` and `sys.stderr` are tagged with the cell
  that made them, including async tasks the cell started.
- Raw file-descriptor output (subprocesses, C extensions) is read by pump
  threads and sent with no cell ID. It is never attributed to a cell.
- After the reader thread takes stdin, the kernel points file descriptor 0 at
  `/dev/null`, so `input()` cannot read protocol frames.

## Rust side

- `tools/ipython.rs`: the `python_repl` tool: schema, sequential mode,
  busy-kernel handling.
- `session_engine/runtime_wiring.rs`: adapts the tool to the provisioner and
  manager; host handlers; skills.
- `kernel/provisioner.rs`: `IpythonKernelProvisioner`: lazy start, prewarm,
  restore, stop, replace.
- `kernel/manager/mod.rs`: `ReplKernelManager`: process state, execution queue,
  buffers.
- `kernel/manager/startup.rs`: spawn, ready handshake, version check.
- `kernel/manager/requests.rs`, `events.rs`: send requests, route events by ID.
- `kernel/manager/host_requests.rs`: dispatch kernel calls to named handlers.
- `kernel/manager/teardown.rs`, `repair.rs`, `snapshot.rs`: shutdown,
  malformed-frame repair, snapshots.
- `kernel/bootstrap/`: python and venv selection, runtime install, skill
  install, bootstrap code.

All paths are under `crates/pa-core/src/`. The daemon adds two things: it
disposes of the kernel when a session ends (`AgentSessionEngine::dispose_kernel`)
and it supplies the host handlers that need the supervisor, such as messaging
and subagents (`extra_host_handlers` in
`crates/pa-daemon/src/agent_engine/lifecycle.rs`).

## Python side

- `repl.py`: process entry, protocol reader, cell compiler and runner,
  snapshots, shutdown, owner watchdog.
- `__init__.py`: the `rlm` namespace: `spawn`, `create_session`, `find_models`,
  `collect`, `list_subagents`, `delete_subagent`, `progress_note`, `harness`,
  `factory`; `host_request`.
- `bash.py`: `bash()`, `BashHandle`, `BashResult`: background shell commands and
  their containment.
- `_winjob.py`: Windows Job Object containment for bash child processes.
- `harness.py`: `HarnessState`: continual harness storage, read and written
  directly from Python.
- `mcp.py`: generic MCP client: HTTP and stdio transports, `list_tools`,
  `call_tool`, reload.
- `mcp_base.py`: `McpIntegration`, the base class for built-in MCP integrations.
- `factory.py`: factory runs and the machine library (templates in `machines/`).
- `skill.py`: CLI entry for Python skills.

All modules are under `prime-agent-runtime/src/rlm/`. The package needs Python
3.11 or later and declares `mcp` and `tyro` as dependencies
(`prime-agent-runtime/pyproject.toml`).

## Running a cell

1. The session adds the `python_repl` tool when it is created. The first call
   asks the provisioner for a running kernel.
2. If none is running, `start_kernel_impl` (`kernel/provisioner.rs`) waits for
   any earlier stop to finish, then sets the cwd, environment and snapshot
   paths.
3. `Inner::do_start` (`kernel/manager/startup.rs`) spawns `python -m rlm.repl`
   with three pipes. It removes internal role variables from the child's
   environment first, and records the PID. This is the Rust-to-Python process
   boundary.
4. Rust waits up to 30 seconds for `ready` and checks the protocol version.
5. Rust restores the saved namespace snapshot, if any, then runs generated
   bootstrap code. The bootstrap binds `rlm`, `bash`, `mcp` and the loaded
   Python skills (`kernel/bootstrap/runtime_code.rs`). Bootstrap runs after
   restore, so live bindings always replace restored copies.
6. To run a cell, `enqueue_request` (`kernel/manager/requests.rs`) takes the
   execution lock, assigns an ID and sends
   `{"type":"execute","id":...,"code":...}`.
7. Python compiles the cell with top-level `await` allowed, runs it, and sends
   `result` or `error`, then `done`.
8. Rust routes `stdout`, `stderr`, `display`, `result`, `error` and `done` by ID
   and builds the tool result. After a successful cell it schedules a snapshot.

Only one cell runs at a time: the tool is sequential, Rust holds an execution
lock, and Python serves execute requests in order. Background asyncio tasks keep
running between cells. An interrupted cell keeps its slot until it really ends,
so a new cell cannot overlap it.

## Calls back into Rust

Python reaches the host with a reverse request: `host_request` from Python,
`host_reply` from Rust, on the same pipes. Rust handles each request in its own
Tokio task and dispatches by type through `HostRequestHandlers`
(`kernel/manager/host_requests.rs`). An unknown type fails with an error. The
Python reader resolves replies outside the cell queue, so a cell that waits for
a reply does not block it.

- `rlm.spawn` (wire type `rlm.run`): `pa-core` `rlm_host` -> daemon
  `SupervisorChildSessions::spawn`.
- `rlm.create_session`: daemon host; creates a top-level session (depth 0 only).
- `rlm.find_models`: `pa-core` model registry.
- `rlm.list_subagents`, `rlm.collect`, `rlm.delete_subagent`: daemon child
  registry (`crates/pa-daemon/src/rlm_children/`).
- `rlm.progress_note`: `pa-core` `rlm_host`.
- `rlm.harness` CRUD: no host call; Python reads and writes the harness file.
- `agent_message.send`: daemon `LinkAgentMessageController`.
- `agent_observe.*`: daemon `LinkAgentObserveController`.
- `compact.status/run`, `refine.status/run`: `pa-core` turn-boundary handlers;
  work is scheduled, not run in the cell.
- `goal.*`: `pa-core` session runtime; goal state stays on the host.
- `mcp.*` (config, refresh, login): `pa-core` `McpManager`; the MCP protocol
  itself runs in Python.

`rlm.spawn` keeps the old wire name `rlm.run` so that kernels and hosts of
different versions stay compatible. The `agent_message`, `agent_observe`,
`compact`, `goal` and `refine` helpers are Python skills under `skills/` that wrap
these host calls.

### Subagents

In a daemon session, `rlm.spawn` creates a real supervised session, not a
Python subprocess:

1. `pa-core` validates the request and calls the injected `RlmSubagentHost`
   (`crates/pa-core/src/session_engine/rlm_host.rs`).
2. The daemon host (`crates/pa-daemon/src/rlm_children/host.rs`) checks depth,
   name, model and thinking level, and prepares the child directory.
3. It sends a `create` command to the supervisor with the parent link and depth.
   The supervisor starts a new worker for the child and appends the spawn to a
   durable ledger (`crates/pa-daemon/src/rlm_ledger.rs`).
4. The parent records the child and returns to Python. `rlm.spawn` returns when
   the child is admitted, not when it finishes.

Print mode has its own in-process host (`crates/pa-cli/src/print_rlm.rs`).
Without any host, a session has no subagents.

## Shutdown, crash and restart

- When a session ends, the worker disposes of its kernel. Rust can flush a last
  snapshot, waits for pending host calls, sends `shutdown`, waits for a bounded
  time, then closes pipes and reaps the bash process groups it recorded
  (`kernel/manager/teardown.rs`).
- The kernel has its own watchdog thread. If the owning process dies, it kills
  its bash handles and exits.
- A malformed protocol frame triggers repair: Rust fails the active cell,
  replaces the kernel, restores and bootstraps again. If the replacement also
  sends a bad frame, it stops (`kernel/manager/repair.rs`).
- After a crash, the next call starts a fresh kernel and restores the last
  snapshot. Snapshots are best effort per variable. Live handles and names that
  start with `_` are skipped, and each object that cannot be serialized is reported.

## Kernel venv and packaging

- **Runtime source.** The runtime is found through `PI_PACKAGE_DIR`, then
  beside the executable (`prime-agent-runtime/`), then in the source checkout
  (`kernel/bootstrap/venv/runtime_source.rs`).
- **Python.** `PRIME_AGENT_KERNEL_PYTHON` selects an existing interpreter.
  Otherwise agx uses its own venv, by default `~/.prime/agent/kernel-venv-agx`;
  `PRIME_AGENT_KERNEL_VENV` overrides it (`kernel/bootstrap/venv/layout.rs`).
  Upstream's default is `kernel-venv`, so by default the two do not share a venv.
- **Setup.** `ensure_kernel_venv` (`kernel/bootstrap/mod.rs`) checks the venv,
  takes a cross-process lock, and builds or updates it with `uv` and Python 3.11.
  It installs the runtime package, the snapshot library and a default package
  set (`DEFAULT_RLM_EXTRA_PACKAGES`). A hash of the runtime sources decides
  when to rebuild.
- **Installer.** `agx --prime-agent-bootstrap` prepares the venv ahead of time
  (`run_runtime_bootstrap` in `crates/pa-cli/src/lib.rs`).
- **Release bundle.** `scripts/package_release.py` copies the executable, the
  `prime-agent-runtime/` and `skills/` directories, README, LICENSE and a version
  manifest.

## Skills in the kernel

A skill is markdown unless it has a `pyproject.toml` and
`src/<name>/__init__.py`, with hyphens in the name changed to underscores; then
it is a Python skill
(`crates/pa-core/src/skills/discovery.rs`). Markdown skills reach the model only
as text: in the system prompt's skill list, or expanded by `/skill:<name>`. For
Python skills, the engine installs changed or missing packages into the venv in
editable mode and imports them in the bootstrap code. A skill that fails to
import gets a placeholder that explains the error when called. Bundled skills
come from `skills/` beside the executable.

## Code map

- `crates/pa-core/src/tools/ipython.rs`: the `python_repl` tool.
- `crates/pa-core/src/kernel/`: provisioner, manager, protocol, bootstrap.
- `crates/pa-core/src/session_engine/rlm_host.rs`, `runtime.rs`,
  `turn_boundary.rs`, `agent_messaging.rs`: host handler registration.
- `crates/pa-daemon/src/rlm_children/`, `rlm_ledger.rs`, `agent_messaging/`:
  supervised subagents and messaging.
- `prime-agent-runtime/src/rlm/`: the Python runtime; `repl.md` is the protocol
  reference.
- `skills/`: bundled markdown and Python skills.
