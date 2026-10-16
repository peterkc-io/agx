#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/python3 "${RUNFILES_DIR}/${TEST_WORKSPACE}/scripts/agx/bazel/test_env.py" "$@"
