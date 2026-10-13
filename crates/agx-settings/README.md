# agx-settings

The fork's JSON settings overlay.

## Scope

This leaf crate owns RFC 7396 merge patches, changed-key-path comparison, and
updates that retain overlay tombstones. It uses the workspace's existing
`serde_json` dependency and has no dependency on a `pa-*` crate.

`src/manager.rs` is the host adapter, compiled inside `pa-core` through its
small settings-manager seam. It keeps base, overlay JSON, and project state
separate and reuses the host's lock and fsync-enabled atomic write.
The adapter also serves the CLI's existing global read/modify/write callback.

## Non-goals

No project-settings change, new settings keys, `extensions` interpretation,
lock protocol, migration format, network access, or plugin behavior.

## Public API

`merge_patch`, `changed_paths`, and `apply_paths` are pure JSON operations.
The host adapter exports `GlobalSettingsStorage` through `pa-core::settings`
for the CLI's existing global-settings boundary.

## Tests

The host crates register `tests/manager.rs` and `tests/cli.rs` as their
`agx_settings` test targets. All fixtures use private temporary directories.
