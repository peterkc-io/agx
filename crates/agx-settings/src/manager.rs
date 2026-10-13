//! agx's global settings overlay, using the host's existing file protocol.

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Result};
use serde_json::{Map, Value};

use super::{load_scope, SettingsError, SettingsManager};
use crate::settings::load::from_value_lenient;
use crate::settings::merge::{deep_merge, merge_patch};
use crate::settings::storage::{FileSettingsStorage, SettingsScope, SettingsStorage};
use crate::settings::types::Settings;

pub(super) struct Overlay {
    base_storage: Arc<dyn SettingsStorage>,
    base: Option<Value>,
    document: Option<Value>,
    previous: Value,
}

impl Overlay {
    fn new(base_storage: Arc<dyn SettingsStorage>) -> Self {
        Self {
            base_storage,
            base: None,
            document: None,
            previous: Value::Null,
        }
    }
}

pub(super) fn create(cwd: PathBuf, agent_dir: PathBuf) -> SettingsManager {
    let base: Arc<dyn SettingsStorage> = Arc::new(FileSettingsStorage::new(&cwd, &agent_dir));
    let overlay: Arc<dyn SettingsStorage> = Arc::new(FileSettingsStorage::overlay(cwd, agent_dir));
    let mut manager = SettingsManager::from_storage(overlay);
    manager.errors.clear();
    manager.agx = Some(Overlay::new(base));
    reload(&mut manager);
    manager
}

pub(super) fn reopen(manager: &SettingsManager) -> SettingsManager {
    let mut fresh = SettingsManager::from_storage(Arc::clone(&manager.storage));
    fresh.errors.clear();
    fresh.agx = Some(Overlay::new(Arc::clone(
        &manager.agx.as_ref().unwrap().base_storage,
    )));
    reload(&mut fresh);
    fresh.apply_overrides(&manager.runtime_overrides);
    fresh
}

pub(super) fn reload(manager: &mut SettingsManager) {
    let mut errors = std::mem::take(&mut manager.errors);
    let state = manager.agx.as_mut().unwrap();
    let (_, base, _) = load_scope(
        state.base_storage.as_ref(),
        SettingsScope::Global,
        &mut errors,
    );
    let (project, _, project_error) = load_scope(
        manager.storage.as_ref(),
        SettingsScope::Project,
        &mut errors,
    );
    let overlay = manager
        .storage
        .read(SettingsScope::Global)
        .and_then(parse_document);
    let (document, overlay_error) = match overlay {
        Ok(value) => (value, None),
        Err(error) => {
            let message = format!("settings-agx.json: {error}");
            errors.push(SettingsError {
                scope: SettingsScope::Global,
                message: message.clone(),
            });
            (None, Some(message))
        }
    };
    let effective = effective_document(base.as_ref(), document.as_ref());
    manager.global = effective
        .as_ref()
        .map_or_else(Settings::default, from_value_lenient);
    state.base = base;
    state.document = document;
    state.previous = settings_value(&manager.global);
    manager.global_raw = effective;
    manager.global_load_error = overlay_error;
    manager.project = project;
    manager.project_load_error = project_error;
    manager.merged = deep_merge(&manager.global, &manager.project);
    manager.errors = errors;
}

fn effective_document(base: Option<&Value>, overlay: Option<&Value>) -> Option<Value> {
    match (base, overlay) {
        (base, Some(patch)) => Some(merge_patch(base.unwrap_or(&Value::Null), patch)),
        (base, None) => base.cloned(),
    }
}

fn parse_document(content: Option<String>) -> Result<Option<Value>> {
    content
        .map(|text| serde_json::from_str(&text).context("parsing settings-agx.json"))
        .transpose()
}

// Typed Settings serializes absent Options as null. Exclude those placeholders
// before comparing snapshots; a removed real field is still a changed null path.
fn settings_value(settings: &Settings) -> Value {
    let mut value = serde_json::to_value(settings).unwrap_or_default();
    remove_unset(&mut value);
    value
}

fn remove_unset(value: &mut Value) {
    if let Value::Object(object) = value {
        object.retain(|_, child| !child.is_null());
        for child in object.values_mut() {
            remove_unset(child);
        }
    }
}

pub(super) fn save_global(manager: &mut SettingsManager) -> Result<()> {
    let state = manager.agx.as_ref().unwrap();
    let changes = agx_settings::changed_paths(&state.previous, &settings_value(&manager.global));
    let mut failure = None;
    manager
        .storage
        .with_lock(
            SettingsScope::Global,
            &mut |current| match parse_document(current).and_then(|document| {
                if changes.is_empty() {
                    return Ok(None);
                }
                let overlay =
                    agx_settings::apply_paths(document.as_ref().unwrap_or(&Value::Null), &changes);
                serde_json::to_string_pretty(&overlay)
                    .map(Some)
                    .map_err(Into::into)
            }) {
                Ok(next) => next,
                Err(error) => {
                    failure = Some(error);
                    None
                }
            },
        )
        .context("updating settings-agx.json")?;
    if let Some(error) = failure {
        return Err(error);
    }
    reload(manager);
    Ok(())
}

pub(super) fn save_field(manager: &mut SettingsManager) {
    if let Err(error) = save_global(manager) {
        manager.errors.push(SettingsError {
            scope: SettingsScope::Global,
            message: error.to_string(),
        });
    }
}

/// Global effective-document adapter for the CLI's existing mutation callback.
pub struct GlobalSettingsStorage {
    base: FileSettingsStorage,
    overlay: FileSettingsStorage,
}

impl GlobalSettingsStorage {
    #[must_use]
    pub fn new(cwd: impl Into<PathBuf>, agent_dir: impl Into<PathBuf>) -> Self {
        let cwd = cwd.into();
        let agent_dir = agent_dir.into();
        Self {
            base: FileSettingsStorage::new(&cwd, &agent_dir),
            overlay: FileSettingsStorage::overlay(cwd, agent_dir),
        }
    }

    fn base_document(&self) -> Value {
        self.base
            .read(SettingsScope::Global)
            .ok()
            .flatten()
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_else(|| Value::Object(Map::new()))
    }
}

impl SettingsStorage for GlobalSettingsStorage {
    fn read(&self, scope: SettingsScope) -> Result<Option<String>> {
        if scope == SettingsScope::Project {
            return self.overlay.read(scope);
        }
        let base = self.base_document();
        let effective = match self.overlay.read(scope).and_then(parse_document) {
            Ok(Some(patch)) => merge_patch(&base, &patch),
            Ok(None) => base,
            Err(error) => {
                eprintln!("settings-agx.json: {error}");
                base
            }
        };
        Ok(Some(serde_json::to_string(&effective)?))
    }

    fn with_lock(
        &self,
        scope: SettingsScope,
        update: &mut dyn FnMut(Option<String>) -> Option<String>,
    ) -> Result<()> {
        if scope == SettingsScope::Project {
            return self.overlay.with_lock(scope, update);
        }
        let mut failure = None;
        self.overlay
            .with_lock(scope, &mut |current| {
                let result = parse_document(current).and_then(|document| {
                    let base = self.base_document();
                    let overlay = document.as_ref().unwrap_or(&Value::Null);
                    let effective = document
                        .as_ref()
                        .map_or_else(|| base.clone(), |patch| merge_patch(&base, patch));
                    let Some(next) = update(Some(serde_json::to_string(&effective)?)) else {
                        return Ok(None);
                    };
                    let next = serde_json::from_str(&next)?;
                    let changes = agx_settings::changed_paths(&effective, &next);
                    if changes.is_empty() {
                        return Ok(None);
                    }
                    serde_json::to_string_pretty(&agx_settings::apply_paths(overlay, &changes))
                        .map(Some)
                        .map_err(Into::into)
                });
                match result {
                    Ok(next) => next,
                    Err(error) => {
                        failure = Some(error);
                        None
                    }
                }
            })
            .context("updating settings-agx.json")?;
        if let Some(error) = failure {
            return Err(error);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn settings_overlay_preserves_the_upstream_fsync_opt_in() {
        let dir = tempfile::tempdir().unwrap();
        let base = dir.path().join("settings.json");
        std::fs::write(&base, b"{\"theme\":\"base\"}\n").unwrap();
        let before_bytes = std::fs::read(&base).unwrap();
        let mut manager = SettingsManager::create(dir.path().join("cwd"), dir.path());
        let before = crate::settings::storage::opt_in_fsync_calls();
        manager.set_theme("overlay".into()).unwrap();
        assert_eq!(crate::settings::storage::opt_in_fsync_calls(), before + 1);
        assert_eq!(std::fs::read(&base).unwrap(), before_bytes);
    }
}
