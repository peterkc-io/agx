---
title: agx architecture
summary: >-
  Index of the architecture pages for the current agx Rust code, with
  reading order and the commits they describe.
describes:
  agx: c79f02406
  upstream: 5f218f780
---

# agx architecture

These pages explain how the current agx code works: which processes run, how a
prompt turn flows through the crates, where the Python kernel sits, what the
fork changes, and which extension points exist today. They are for people and
agents who need to understand the code before they change it.

The pages describe agx `main` at `c79f02406`. Its upstream code is
PrimeIntellect-ai/prime-agent at `5f218f780`. Each page repeats these commits
in its front matter (`describes`). When the code moves past them, check the
claims against the source before you rely on them.

The pages name files, modules and types, not line numbers. Use `rg` or your
editor's symbol search to find them. Paths are relative to the repository root.

## Reading order

| Page                                    | Read it to learn                                    |
| --------------------------------------- | --------------------------------------------------- |
| [Overview](overview.md)                 | The processes, crates, entry points and main rules  |
| [Processes and sessions](processes.md)  | Supervisor, workers, wire, persistence and recovery |
| [A prompt turn](prompt-turn.md)         | What happens from a prompt to the end of the turn   |
| [Python kernel](kernel.md)              | How Rust starts and talks to the Python REPL kernel |
| [Fork overlay](fork-overlay.md)         | Where agx changes upstream behavior, and why        |
| [Extension points](extension-points.md) | The hooks and seams that exist in the code today    |

## Related documents

- [`AGENTS.md`](../../../AGENTS.md): upstream rules for crate scope, dependency
  direction and merge gates.
- Each crate's `README.md` under [`crates/`](../../../crates): scope, non-goals and
  public API, written upstream. Some parts are out of date; the
  [overview](overview.md#where-upstream-docs-differ-from-the-code) lists the
  differences found.
- [`docs/fork/FORK.md`](../FORK.md), [`FEATURES.md`](../FEATURES.md) and
  [`SEAMS.md`](../SEAMS.md): what the fork is, its features, and every upstream
  file it changes.
- [`prime-agent-runtime/src/rlm/repl.md`](../../../prime-agent-runtime/src/rlm/repl.md):
  the kernel wire protocol reference.

## Scope

These pages describe the code as it is. They do not describe the planned plugin
system, which is not implemented. The seam checker
(`scripts/agx/check_seams.py`) already treats `docs/plugins/` and `plugins/` as
fork-owned paths.
