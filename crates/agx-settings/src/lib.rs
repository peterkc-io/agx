//! RFC 7396 overlay operations; persistence remains with the host settings store.

use serde_json::{Map, Value};

/// Global merge-patch document next to the read-only upstream settings.
pub const OVERLAY_FILE_NAME: &str = "settings-agx.json";

/// Apply an RFC 7396 merge patch without changing either input.
#[must_use]
pub fn merge_patch(base: &Value, patch: &Value) -> Value {
    let Value::Object(patch) = patch else {
        return patch.clone();
    };
    let mut result = base.as_object().cloned().unwrap_or_default();
    for (key, value) in patch {
        if value.is_null() {
            result.remove(key);
        } else {
            let previous = result.get(key).unwrap_or(&Value::Null);
            result.insert(key.clone(), merge_patch(previous, value));
        }
    }
    Value::Object(result)
}

/// Changed key paths, with null marking removals. Arrays replace as one value.
#[must_use]
pub fn changed_paths(before: &Value, after: &Value) -> Vec<(Vec<String>, Value)> {
    let mut changes = Vec::new();
    collect_changes(before, after, &mut Vec::new(), &mut changes);
    changes
}

fn collect_changes(
    before: &Value,
    after: &Value,
    path: &mut Vec<String>,
    changes: &mut Vec<(Vec<String>, Value)>,
) {
    if before == after {
        return;
    }
    if let (Value::Object(before), Value::Object(after)) = (before, after) {
        for (key, previous) in before {
            path.push(key.clone());
            collect_changes(
                previous,
                after.get(key).unwrap_or(&Value::Null),
                path,
                changes,
            );
            path.pop();
        }
        for (key, next) in after {
            if !before.contains_key(key) {
                path.push(key.clone());
                changes.push((path.clone(), next.clone()));
                path.pop();
            }
        }
    } else {
        changes.push((path.clone(), after.clone()));
    }
}

/// Update only changed paths in a fresh overlay, retaining null tombstones.
#[must_use]
pub fn apply_paths(overlay: &Value, changes: &[(Vec<String>, Value)]) -> Value {
    let mut result = overlay.clone();
    for (path, value) in changes {
        let mut slot = &mut result;
        for key in path {
            if !slot.is_object() {
                *slot = Value::Object(Map::new());
            }
            slot = &mut slot[key];
        }
        *slot = value.clone();
    }
    result
}
