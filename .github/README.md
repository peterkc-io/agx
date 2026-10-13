# agx

A Prime Agent fork with a separate executable and runtime namespace.

## Why fork

- [Separate daemon and kernel namespaces](../docs/fork/FORK.md) let agx run beside upstream.
- [Startup environment reset](../docs/fork/FORK.md) prevents inherited upstream roles from selecting a fork process mode.
- [Updates, telemetry, and trace uploads are disabled](../docs/fork/FORK.md) in the foundation.
- [A local native bundle installer](../docs/fork/INSTALL.md) leaves the upstream installation intact.
- [A settings overlay](../docs/fork/FEATURES.md) keeps agx global edits out of upstream's `settings.json`.
- Plugins remain planned, not implemented.

## Start here

Read [the agx features, fixes and compatibility limits](../docs/fork/FEATURES.md).
Use [the local installation instructions](../docs/fork/INSTALL.md), not the
upstream installer, for `agx`.

Sessions and base settings are shared. agx writes its own settings overlay.
Root `README.md` remains
upstream material. [The seam ledger](../docs/fork/SEAMS.md) records changes to
upstream files.

## Acknowledgements

This fork builds on Prime Intellect's upstream Prime Agent and its use of
ratatui and vouch. The extension design uses **patterns and ideas adapted from**
[OpenAI Codex](https://github.com/openai/codex), licensed under Apache-2.0.
This statement credits design sources, not copied Codex code.
