---
title: Fork overlay
summary: >-
  Where and how agx changes upstream Prime Agent behavior: process identity
  and sockets, the kernel venv, the settings overlay, disabled telemetry,
  traces and updates, and how the changed upstream files group by subsystem.
describes:
  agx: c79f02406
  upstream: 5f218f780
---

# Fork overlay

agx changes upstream behavior in a few narrow places and leaves the engine, the
wire protocol and the session format alone. This page explains each change and
where it lives in the code. [`FORK.md`](../FORK.md) gives the fork's purpose and
user-facing limits; [`SEAMS.md`](../SEAMS.md) lists every changed upstream file.

## What agx shares with upstream, and what it separates

```text
upstream prime-agent                          agx
--------------------                          ---
prime-agent-<uid>/ sockets      separate      agx-<uid>/ sockets
kernel-venv                     separate      kernel-venv-agx
settings.json            shared (agx reads; writes go to settings-agx.json)
sessions/, agent dir            shared        sessions/, agent dir
updates, telemetry, traces      upstream      disabled in agx
```

The two products can run side by side on one machine. They see the same
sessions and the same base settings. agx refuses the upstream daemon's known
socket and pipe names; an upstream daemon on an unrelated custom path is not
recognized (see [Process identity and sockets](#process-identity-and-sockets)).
Session leases (see [Processes and sessions](processes.md#state-on-disk)) stop
both from running one session at the same time.

## Where fork code lives

- **`crates/agx-identity`**: a leaf crate with no dependencies. It owns process
  isolation, upstream socket refusal, and the update and trace policy constants.
  `pa-types` re-exports it as `pa_types::fork_identity`, so existing upstream
  crates reach it through their normal `pa-types` dependency.
- **`crates/agx-settings`**: the RFC 7396 merge-patch functions
  (`merge_patch`, `changed_paths`, `apply_paths`) and the overlay file name. Its
  `src/manager.rs` is a host adapter that `pa-core` compiles as its own
  `agx_overlay` module through `#[path]`.
- **`scripts/agx/`**: operator tools, not runtime code. They cover local
  install (`install_local.py`), the seam check (`check_seams.py`) and upstream
  sync (`sync.py`, `sync_layers.py`).
- **`docs/fork/`**: these docs and the other fork documents.
- **Edits to upstream files**: listed one per row in `SEAMS.md`. The grouping
  [below](#changed-upstream-files) shows what each group does.

`scripts/agx/check_seams.py` treats these paths as fork-owned and needs no
ledger row for them: `docs/fork/`, `docs/plugins/`, `plugins/`, `scripts/agx/`,
`crates/agx-*/`, `.github/workflows/agx-*.yml`, `.github/README.md`,
`.github/AGX_VOUCHED.td` and `prime-agent-runtime/test/test_agx_settings.py`.
Every other changed file needs a row.

## Process identity and sockets

`main` in `crates/pa-cli/src/main.rs` calls `initialize_process` before it
starts any thread. For a fresh process, not one started by agx itself, it:

1. removes internal daemon role variables and the upstream path variables
   `PRIME_AGENT_DAEMON_SOCKET`, `PRIME_AGENT_KERNEL_VENV`,
   `PRIME_AGENT_KERNEL_OWNER_PID` and `PI_PACKAGE_DIR`;
2. sets `AGX_PROCESS=1`, so agx's own child processes keep the values agx
   gives them.

Before spawning, the bash tool and the kernel strip internal role variables
from the child environment (`strip_internal_environment`,
`strip_kernel_internal_environment`). The kernel keeps only the orphan-journal
path.

agx uses its own endpoint names: `agx-<uid>/daemon.sock` and
`worker-*.sock` on Unix, `agx-daemon` and `agx-worker-*` pipes on Windows
(`crates/pa-daemon/src/platform/paths.rs`). `reject_upstream_socket` refuses a
path that resolves into an upstream socket directory or pipe prefix. It is
checked at each boundary:

- CLI socket resolution (`resolve_daemon_socket_path` in
  `crates/pa-cli/src/config.rs`);
- daemon socket setup, before it creates directories or removes stale sockets
  (`prepare_socket_path` in `crates/pa-daemon/src/socket.rs`);
- every connect and bind in `crates/pa-types/src/platform/transport.rs`, on Unix
  and Windows.

`AGX_PROCESS` does not bypass the refusal. The check is by path and name. It
does not probe the daemon, so it cannot recognize an upstream daemon on an
unrelated custom path.

## Kernel venv

The default kernel venv is `~/.prime/agent/kernel-venv-agx`, and the XDG
fallback uses the same name (`kernel_venv_dir` in
`crates/pa-core/src/kernel/bootstrap/venv/layout.rs`). Because agx sets the
default in code, it does not need to export a venv variable to its children.
Some repair hints in the kernel bootstrap code still name upstream's
`kernel-venv`.

## Settings overlay

Global settings writes go to `settings-agx.json`, an overlay beside upstream's
`settings.json`. agx never writes the base file.

```text
read:   settings.json  --merge_patch-->  + settings-agx.json  --deep_merge-->  + project settings
write:  changed key paths only  ------------------------------->  settings-agx.json
```

- **Read.** The adapter's `reload` (`crates/agx-settings/src/manager.rs`) reads
  the base, the overlay and the project settings separately. It applies the
  overlay with RFC 7396 `merge_patch`, then the project settings with upstream's
  existing `deep_merge`. If the overlay is malformed, it records an error and
  uses the base alone.
- **Write.** `save_global` compares the new settings with the previous snapshot,
  takes the existing settings lock, rereads the overlay, and writes only the
  changed key paths. A `null` in the overlay deletes a key and is kept as a
  marker, so a later upstream value does not reappear. A malformed overlay
  refuses the write. The lock, reread and fsync'd atomic write are upstream's
  `FileSettingsStorage` code, unchanged.
- **CLI.** `GlobalSettingsStorage` gives the CLI's existing read, modify and
  write callback the effective settings, then writes only what the callback
  changed (used by `crates/pa-cli/src/mcp_command.rs`).
- **Python.** The kernel reads settings on its own for two switches: the factory
  opt-in and `harnessRefinements`. Both apply the overlay first
  (`prime-agent-runtime/src/rlm/factory.py`, `harness.py`). The Rust factory
  check in `crates/pa-core/src/refinement/mod.rs` does the same.

The overlay adds no settings keys. `Settings` keeps unknown keys, but nothing in
agx reads an `extensions` key.

## Telemetry, traces and updates

- **Usage telemetry.** In release builds, `telemetry_switch` returns
  `ForkDisabled` before it reads the environment or settings, and
  `telemetry_endpoint()` returns `None` in every build
  (`crates/pa-core/src/session_engine/telemetry/status.rs`). Debug builds keep
  upstream's switch so upstream tests still run, but they still have no
  endpoint. The upstream client still creates `telemetry.json` for its
  installation ID, a local file in the shared agent directory.
- **Trace uploads.** A public single upload checks `TRACES_DISABLED` before it
  builds a request, even with force options
  (`crates/pa-core/src/agent_traces/upload.rs`). Upload-all lists candidate
  session files and then calls that same guarded upload for each, so it reads
  local headers but sends nothing (`upload_all.rs`). Continuous uploads are
  refused outside tests (`continuous.rs`). `/share` and `/traces` report trace
  sharing as unavailable.
- **Updates.** The update commands, the installer driver and the TUI's
  `/update` refuse before any upstream update code runs, and print the local
  install instructions (`public_command.rs`, `installer_update.rs`,
  `client_update.rs` in `crates/pa-cli/src/`). The upstream update code is still
  in the tree but is not reachable from these commands.

## Changed upstream files

At `c79f02406`, compared with upstream `5f218f780`, 166 paths differ. 36 of
them are fork-owned paths. The other 130 are edits to upstream files, and each
has a row in `SEAMS.md`. They fall into these groups:

| Group                                  | Files | What the edits do                               |
| -------------------------------------- | ----: | ----------------------------------------------- |
| Workspace and executable identity      |     9 | Fork crates, `agx` binary, `initialize_process` |
| Socket namespace and refusal           |    10 | agx endpoint names, upstream socket refusal     |
| Settings overlay                       |    13 | Global writes to the overlay, overlay readers   |
| Telemetry and trace uploads            |    14 | Telemetry off, upload guards, sharing off       |
| Kernel venv and process roles          |    37 | `kernel-venv-agx`, environment stripping        |
| Update refusal                         |     7 | Refuse updates with install instructions        |
| CLI test fixtures and host portability |    40 | `agx` binary in tests, macOS and Linux guards   |

Most rows in the two largest groups change tests, not runtime code. To see
the current list, run `python3 scripts/agx/check_seams.py`, which fails on a
missing or stale row.
