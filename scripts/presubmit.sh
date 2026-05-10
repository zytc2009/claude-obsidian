#!/usr/bin/env bash
# Pre-commit / pre-push checks for claude-obsidian.
#
# Lightweight by design — this is a single-process Python skill, not a
# multi-tier app. Modeled after MultiAgent2's scripts/presubmit.sh but
# trimmed to what makes sense here.
#
# Usage:
#   bash scripts/presubmit.sh
#
# Exit code: 0 = all green; non-zero = at least one step failed.
#
# Future steps to add when toolchain is stable:
#   - ruff check / ruff format --check
#   - mypy
#   - pip-audit

set -u
set -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAILED=()
START_TIME=$(date +%s)

run_step() {
  local name="$1"; shift
  local step_start=$(date +%s)
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  ▶ $name"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if "$@"; then
    local elapsed=$(( $(date +%s) - step_start ))
    echo "  ✓ $name  (${elapsed}s)"
  else
    local elapsed=$(( $(date +%s) - step_start ))
    echo "  ✗ $name  FAILED  (${elapsed}s)"
    FAILED+=("$name")
  fi
}

# Pick a Python interpreter: prefer .venv if present, otherwise python on PATH.
PYTHON="python"
if [ -x ".venv/Scripts/python.exe" ]; then
  PYTHON=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
fi

# ---------- pytest ----------
run_step "pytest" "$PYTHON" -m pytest -q --no-header

# ---------- module import smoke ----------
# Catches relative-import regressions in the layered modules even when
# pytest isn't routed through them yet (e.g. CLI script-mode loaders).
run_step "import smoke (package mode)" "$PYTHON" -c "
import skills.obsidian.workspace
import skills.obsidian.frontmatter
import skills.obsidian.note_repository
import skills.obsidian.events
import skills.obsidian.runs
import skills.obsidian.pipeline
import skills.obsidian.templates
import skills.obsidian.index
import skills.obsidian.section_ops
import skills.obsidian.log_writer
import skills.obsidian.linker
import skills.obsidian.session_helpers
import skills.obsidian.ingest_service
import skills.obsidian.knowledge_service
import skills.obsidian.live_note
import skills.obsidian.cli
import skills.obsidian.obsidian_writer
"

# Note: script-mode CLI loading (``python obsidian_writer.py``) is already
# exercised by tests/test_obsidian_writer.py's subprocess assertions.

# ---------- summary ----------
ELAPSED=$(( $(date +%s) - START_TIME ))
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "  ALL GREEN  (${ELAPSED}s)"
  exit 0
else
  echo "  ${#FAILED[@]} STEP(S) FAILED  (${ELAPSED}s)"
  for name in "${FAILED[@]}"; do
    echo "    - $name"
  done
  exit 1
fi
