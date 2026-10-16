---
title: Processes and sessions
summary: >-
  How the agx supervisor, session workers and clients run and talk to each
  other, where session state is stored on disk, and how the daemon recovers
  from crashes and restarts.
describes:
  agx: c79f02406
  upstream: 5f218f780
---

# Processes and sessions

The daemon splits work across processes. A supervisor process owns routing and
supervision. Each active session runs in its own worker process. Clients such as
the terminal UI connect to the supervisor and, for an attached session, directly
to its worker. This page explains those processes, the two wire formats between
them, the files they keep on disk, and the recovery paths.

Print, JSON and RPC modes do not use these processes; see
[Headless modes](#headless-modes).

## Processes

```text
 agx (TUI client)       agx --mode daemon (supervisor)    agx worker (one per session)
 ----------------       ------------------------------    ----------------------------
 DaemonClient --JSONL-> Supervisor, SessionRegistry,
              <-events- ResidentWorker per worker
                             |  spawns, watches, restarts
                             +-------------------------->  Worker::serve
                             <------ worker_register ----  SessionCore
                                                           AgentSessionEngine
                                                           (starts the kernel process)
 DaemonClient ------ direct link: private frames ------->  session commands
```

### Client

The interactive CLI resolves the socket path, probes the supervisor with a hello
exchange, and starts it if it is missing. It starts the supervisor as a detached
copy of its own executable with `--mode daemon --daemon-socket <path>`, in a new
terminal session with null stdio (`spawn_supervisor_detached` in
`crates/pa-cli/src/interactive_mode/daemon.rs`). The UI itself never starts a
supervisor.

`pa-tui` then opens a `DaemonClient` (`crates/pa-tui/src/daemon_client.rs`).
Separate Tokio tasks write command envelopes and read JSON lines. These are
tasks inside the client process, not more processes.

### Supervisor

`Supervisor` (`crates/pa-daemon/src/supervisor.rs`) owns configuration, the
`SessionRegistry` of resident workers, client connections and subscriptions,
worker routing and the roster. It does not run session engines.

- `launch_worker` (`supervisor/worker_lifecycle.rs`) normalizes a create
  request, chooses cwd, model and session options, writes a durable worker
  descriptor, and starts the worker. Concurrent opens of the same session file
  share one launch.
- `spawn_worker_process` (`supervisor/supervision.rs`) runs the current
  executable with `worker`, null stdin and stdout, a per-worker stderr log, the
  chosen cwd, internal identity variables and a new process group.
- The supervisor watches each child. On an unexpected exit it restarts the
  worker with backoff: 250 ms at first, capped at 30 s. After five consecutive
  failures it gives up. A worker that lived at least 30 s resets the failure
  count.

### Session worker

`run_worker` (`crates/pa-daemon/src/worker.rs`) reads its `WorkerConfig`,
starts self-registration with the supervisor, and serves its own endpoint.
`Worker::serve` (`worker/connection.rs`) binds the endpoint, takes ownership of
the recovery journal, starts orphan monitoring, and handles each connection in
its own task. `SessionCore` (`worker/session_core.rs`) holds the live session
store, queues and sequencing that connection and turn tasks share.

The worker registers over a separate JSONL connection to the supervisor. It
reads `daemon_hello`, sends `worker_register`, and keeps the link open. If the
link drops, it retries with exponential backoff. If the supervisor refuses it
outright, the worker retires instead of holding a session lease nobody can see
(`crates/pa-daemon/src/registration.rs`).

## Wire protocols

The protocol keeps its upstream identity, `prime-agent.daemon` version 7, so
agx stays wire-compatible with upstream (`crates/pa-types/src/daemon/mod.rs`).
All shared wire types live in `crates/pa-types/src/daemon/`.

**Supervisor socket: JSONL.** Each line is a `DaemonCommandEnvelope` (frame type
`command`, request ID, protocol info, optional client ID, and a
`DaemonCommand`) or a bare command. Replies are `DaemonResponse` values.
Unsolicited messages are `DaemonOutbound` values: `daemon_hello`, roster
changes, session events, attach and resync state, and chunked snapshots.

**Worker endpoint: private frames.** Each frame is an 8-byte prefix with two
big-endian `u32` lengths, then a JSON header and a binary payload
(`crates/pa-types/src/daemon/framing.rs`). The default limits are 1 MiB for the
header and 1 GiB for the payload. `DaemonWorkerFrameHeader` marks a frame as a
command or an outbound message.

**Direct attach.** Before it attaches, the UI asks the supervisor for a direct
transport to the session's worker (`upgrade_direct` in `daemon_client.rs`). The
supervisor mints a single-use ticket bound to that worker incarnation and
purpose, valid for 10 seconds (`crates/pa-daemon/src/peer_tickets.rs`). The UI
authenticates to the worker with `peer_auth`; it never sees the worker's
bootstrap token. After that:

- session-plane commands for that session go over the direct link;
- control commands stay on the supervisor connection;
- if the direct attach fails, the UI drops it and attaches through the
  supervisor instead.

The split between session-plane and control commands is a table in
`crates/pa-types/src/daemon/plane.rs`, shared by the worker and the client.

**Worker to worker.** An agent message to another session first tries a direct
peer connection to the target worker, with a `worker` purpose ticket
(`deliver_message_over_peer_transport` in `crates/pa-daemon/src/peer_client.rs`).
Only when the direct route is unavailable does it go through the supervisor
(`crates/pa-daemon/src/agent_messaging/message.rs`). Once a message is sent, a
lost reply is reported as lost, not as failed.

## Endpoints

| Platform | Supervisor endpoint             | Worker endpoint                     |
| -------- | ------------------------------- | ----------------------------------- |
| Unix     | `$TMPDIR/agx-<uid>/daemon.sock` | `worker-<hash>-<id>.sock`, same dir |
| Windows  | `\\.\pipe\agx-daemon`           | `\\.\pipe\agx-worker-...`           |

`$TMPDIR` falls back to `/tmp`. On Unix systems other than Linux, the directory
falls back to `/tmp/agx-<uid>` when a worker socket path would be too long
(`crates/pa-daemon/src/platform/paths.rs`). The CLI picks the socket from
`--daemon-socket`, then `PRIME_AGENT_DAEMON_SOCKET`, then the platform default,
and then refuses any upstream socket path (`resolve_daemon_socket_path` in
`crates/pa-cli/src/config.rs`). See [Fork overlay](fork-overlay.md#process-identity-and-sockets).

The daemon discovery commands (`status`, `doctor`, `shutdown`) live in
`crates/pa-cli/src/daemon_discovery/`. On Unix they take a census of listening
sockets. On Windows, where a daemon uses one fixed named pipe, they probe that
pipe. Every scan is limited to one `DaemonStateRoot`.

## State on disk

Session history, worker records and recovery state are separate stores. agx
shares the session store with upstream Prime Agent and uses its own names only
for the socket-derived parts.

- **Agent directory:** `~/.prime/agent`, or `PRIME_AGENT_CODING_AGENT_DIR`.
  Shared with upstream.
- **Session history:** `<agent-dir>/sessions/<session-id>.jsonl`, or the
  directory in `PRIME_AGENT_SESSION_DIR`. Shared with upstream.
- **Worker descriptors:** `<agent-dir>/daemon-workers/<socket-hash>/<worker-id>.json`,
  written by the supervisor. The socket hash keeps agx and upstream apart.
- **Recovery journals:** in the same descriptor directory, written by workers.
- **Session leases:** `<agent-dir>/session-leases/<sha256-of-path>.lock`, taken
  by whichever process runs the session.

**Session history.** New session IDs are UUIDv7. The first line of a session
file is a `session` header, version 3, with the durable session ID, timestamp,
cwd and optional parent and RLM depth. Every later line is an entry with a type,
an entry ID, a parent ID and a timestamp. The parent links form a tree, so
branches share one file (`crates/pa-types/src/session.rs`,
`crates/pa-daemon/src/session_store/`). Normal writes append a line, flush and
fsync. If the file ends in a torn line, the writer adds a newline first. Rewrite
and repair operations also exist: `SessionFile::rewrite` writes a synced
temporary file and renames it over the old one.

**Descriptors.** A worker descriptor records the create payload and launch
identity the supervisor needs to adopt or relaunch the worker
(`crates/pa-daemon/src/descriptor.rs`).

**Recovery journals.** The journal holds the latest busy and operation state and
snapshots of the steering and follow-up queues. It is separate from the
conversation history. A `.writer-lock` file stops two workers from writing the
same journal (`crates/pa-daemon/src/journal.rs`).

**Leases.** A worker must take a runtime lease on a session file before it
opens it. The lease is a lock directory with an `owner.json` that records the
owner token, PID, process start identity and active session ID. A live owner
blocks a second one (`acquire_runtime_session_lease` in
`crates/pa-daemon/src/lease.rs`). agx does not change this file, and the lease
directory is in the shared agent directory. So the same lease also stops an
upstream daemon and an agx daemon from running one session at the same time.

## Recovery

**Worker crash.** The supervisor relaunches the worker and replays the
descriptor's create payload. The new worker reopens the history and restores
the queue lanes from the journal (`relaunch_worker` in
`supervisor/supervision.rs`). Images attached to queued prompts are not
restored.

**Supervisor restart.** A new supervisor starts serving at once and adopts
existing workers from their descriptors in parallel, so workers can register
immediately (`Supervisor::run`, `supervisor/adoption.rs`):

- a live worker is authenticated and reused;
- a dead idle worker stays down;
- a dead worker with valid busy evidence is relaunched;
- a durable stop record wins over liveness, so a stopped worker is never revived.

**Supervisor gone.** A worker that cannot reach its supervisor does not exit at
once. When idle, it shuts down after five minutes without a supervisor. Ongoing
work postpones the exit. It never starts a new supervisor
(`crates/pa-daemon/src/supervisor_lost.rs`).

**UI connection lost.** If the direct worker link breaks, the UI attaches again
through the supervisor. It retries for up to one minute, with a backoff that
starts at 100 ms and is capped at 2 s. It reattaches by durable session ID. If
the supervisor connection itself drops unexpectedly, the UI retries for up to
10 minutes; after an announced shutdown it retries for 60 seconds and never
starts a daemon (`crates/pa-tui/src/interactive/reconnect.rs`).

**Resume a saved session.** Lookup searches live sessions in the current
directory first, then all live sessions, then the archive. An archived match is
moved back to the live store (`crates/pa-daemon/src/session_catalog.rs`).

## Headless modes

- **Print and JSON.** `print_mode_main` (`crates/pa-cli/src/print_runtime.rs`)
  takes a session lease, builds the session engine in-process, and runs the
  prompts. Subagents are in-process session nodes (`crates/pa-cli/src/print_rlm.rs`).
  Every exit path disposes of them, so no child outlives the process.
- **RPC.** `rpc_mode_main` builds an in-process engine, hands its lease to the
  RPC handle, and serves JSON lines on stdin and stdout
  (`crates/pa-daemon/src/rpc/`).
- **ACP.** `acp_mode_main` makes sure a supervisor is running, creates a
  daemon session, and bridges ACP JSON-RPC on stdin and stdout to daemon
  commands and events (`crates/pa-daemon/src/acp/`). ACP is not RPC under
  another name.

## Code map

- `crates/pa-cli/src/interactive_mode/daemon.rs`: supervisor probe and start.
- `crates/pa-daemon/src/supervisor.rs` and `supervisor/`: supervisor state,
  adoption, worker launch, restart and routing.
- `crates/pa-daemon/src/worker.rs` and `worker/`: worker entry, endpoint,
  session open, turns and queues.
- `crates/pa-daemon/src/registry.rs`, `registration.rs`, `descriptor.rs`:
  resident workers, worker registration and durable worker records.
- `crates/pa-daemon/src/session_store/`, `journal.rs`, `lease.rs`: history,
  recovery state and single-owner leases.
- `crates/pa-daemon/src/peer.rs`, `peer_tickets.rs`, `peer_client.rs`: direct
  links and tickets.
- `crates/pa-types/src/daemon/`: commands, responses, events, planes and framing.
- `crates/pa-tui/src/daemon_client.rs`, `session_ui/lifecycle.rs`,
  `interactive/reconnect.rs`: client attach and reconnect.
