# Fork-owned Bazel recipes. Local cache locations belong in a user bazelrc.
bazel-gen:
    python3 scripts/agx/gen_bazel.py

bazel-check:
    python3 scripts/agx/gen_bazel.py --check

[private]
bazel-lock:
    #!/usr/bin/env sh
    set -eu
    if [ ! -f scripts/agx/Cargo.Bazel.lock ]; then
        CARGO_BAZEL_REPIN=workspace bazelisk query @crates//:all > /dev/null
    fi
    if ! git diff --exit-code -- Cargo.lock; then
        echo "Bazel bootstrap found a changed Cargo.lock; stop and review it." >&2
        exit 1
    fi

bazel-test: bazel-lock
    bazelisk test //...
