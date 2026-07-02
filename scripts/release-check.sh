#!/bin/sh
# Release gate for coop-dax-review — run by `make release-check` and .githooks/pre-commit.
# Fast (<1s), no network, no venv. POSIX sh (works on macOS bash 3.2 and Git Bash on Windows).
#
# Checks:
#   1. `__version__ = "X.Y.Z"` is extractable from src/coop_dax_review/__init__.py with the
#      same pattern publish.yml uses to gate `v*` release tags.
#   2. pyproject.toml still derives the package version from that same file (hatchling
#      dynamic versioning) — so the wheel version is the gated version.
#   3. The bundled standards file is byte-identical to the authored canon (the JSON
#      contract's standards sha256 provenance depends on this).

set -eu
cd "$(dirname "$0")/.."

fail() {
    echo "release-check: FAIL — $1" >&2
    exit 1
}

# 1) version single-source — mirrors publish.yml: __version__ = "([^"]+)"
VERSION=$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' src/coop_dax_review/__init__.py)
[ -n "$VERSION" ] || fail 'no `__version__ = "..."` line in src/coop_dax_review/__init__.py (publish.yml tag gate would fail)'
echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+' \
    || fail "__version__ '$VERSION' does not look like X.Y.Z"

# 2) hatchling must read the version from the same file publish.yml greps
grep -q 'path = "src/coop_dax_review/__init__.py"' pyproject.toml \
    || fail 'pyproject.toml [tool.hatch.version] no longer points at src/coop_dax_review/__init__.py'

# 3) bundled standards == authored canon, byte for byte
cmp -s docs/standards.md src/coop_dax_review/data/standards.md \
    || fail 'docs/standards.md and src/coop_dax_review/data/standards.md differ — fix with: cp docs/standards.md src/coop_dax_review/data/standards.md'

echo "release-check: OK — version $VERSION, standards in sync"
