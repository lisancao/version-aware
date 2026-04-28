#!/usr/bin/env bash
# version-check.sh — staleness-guard PreToolUse hook
# Checks installed library versions against training cutoff map.
# Outputs warnings ONLY when version gaps are found. Silent when clean.
#
# Performance:
# - One `pip list --format=json` call (not 22 `pip show`)
# - 60-second cache in /tmp keyed by python interpreter path
# - Hard ceiling: ~500ms cold, ~10ms warm

set -uo pipefail

CACHE_TTL_SEC=60
CACHE_DIR="${TMPDIR:-/tmp}/staleness-guard-$(id -u)"
mkdir -p "$CACHE_DIR" 2>/dev/null

# ---------------------------------------------------------------------------
# Training cutoff version map
# Conservative: the last version we're confident the model was trained on.
# When installed version > cutoff, flag it.
# Format: "library cutoff_major.cutoff_minor"
# ---------------------------------------------------------------------------
read -r -d '' CUTOFF_MAP <<'EOF'
pyspark 3.5
delta-spark 2.4
pandas 2.1
numpy 1.26
scikit-learn 1.3
tensorflow 2.14
torch 2.1
mlflow 2.9
dbt-core 1.7
polars 0.19
dask 2023.11
ray 2.8
kafka-python 2.0
kubernetes 28.1
pyarrow 14.0
xgboost 2.0
lightgbm 4.1
transformers 4.36
datasets 2.15
pydantic 2.5
fastapi 0.104
sqlalchemy 2.0
alembic 1.13
EOF

NODE_CUTOFFS=$(cat <<'EOF'
react 18
next 14
typescript 5.2
webpack 5.88
vite 4.4
prisma 5.6
express 4.18
EOF
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Compare two version strings. Echoes "gap" if installed > cutoff, empty otherwise.
# Strips dev/rc/post tags before comparison. Major-then-minor only.
version_exceeds_cutoff() {
  local installed="$1"
  local cutoff="$2"

  installed=${installed//[!0-9.]/}
  cutoff=${cutoff//[!0-9.]/}

  local IFS=.
  read -r inst_major inst_minor _ <<< "$installed"
  read -r cut_major cut_minor _ <<< "$cutoff"

  inst_major=${inst_major:-0}
  inst_minor=${inst_minor:-0}
  cut_major=${cut_major:-0}
  cut_minor=${cut_minor:-0}

  if [ "$inst_major" -gt "$cut_major" ] 2>/dev/null; then
    echo "gap"
  elif [ "$inst_major" -eq "$cut_major" ] 2>/dev/null && [ "$inst_minor" -gt "$cut_minor" ] 2>/dev/null; then
    echo "gap"
  fi
}

# Return cached pip list JSON or refresh if expired/missing
get_pip_list_cached() {
  local pip_cmd="${1:-pip}"
  local cache_key
  cache_key=$(command -v "$pip_cmd" 2>/dev/null | sha1sum 2>/dev/null | cut -c1-12)
  [ -z "$cache_key" ] && cache_key="default"
  local cache_file="$CACHE_DIR/pip-list-$cache_key.json"

  if [ -f "$cache_file" ]; then
    local age
    age=$(( $(date +%s) - $(stat -c %Y "$cache_file" 2>/dev/null || echo 0) ))
    if [ "$age" -lt "$CACHE_TTL_SEC" ]; then
      cat "$cache_file"
      return 0
    fi
  fi

  "$pip_cmd" list --format=json --disable-pip-version-check 2>/dev/null > "$cache_file"
  cat "$cache_file"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

WARNINGS=()

# Python: one pip list call, indexed by name
PIP_CMD=""
if command -v pip &>/dev/null; then
  PIP_CMD="pip"
elif command -v pip3 &>/dev/null; then
  PIP_CMD="pip3"
fi

if [ -n "$PIP_CMD" ]; then
  pip_json=$(get_pip_list_cached "$PIP_CMD")
  if [ -n "$pip_json" ] && command -v python3 &>/dev/null; then
    # Single python invocation handles all lookups + comparisons.
    # Echoes one line per gap: "lib installed cutoff"
    py_warnings=$(python3 - <<PY
import json, re, sys
pkgs_json = """$pip_json"""
cutoff_map = """$CUTOFF_MAP"""

try:
    pkgs = {p['name'].lower(): p.get('version','') for p in json.loads(pkgs_json)}
except Exception:
    sys.exit(0)

def strip_nonver(v):
    return re.sub(r'[^0-9.].*$', '', v)

def major_minor(v):
    parts = strip_nonver(v).split('.')
    try:
        major = int(parts[0]) if parts and parts[0] else 0
    except ValueError:
        major = 0
    try:
        minor = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    except ValueError:
        minor = 0
    return major, minor

for line in cutoff_map.strip().splitlines():
    line = line.strip()
    if not line:
        continue
    parts = line.split()
    if len(parts) < 2:
        continue
    lib, cutoff = parts[0], parts[1]
    installed = pkgs.get(lib.lower())
    if not installed:
        continue
    inst_maj, inst_min = major_minor(installed)
    cut_maj, cut_min = major_minor(cutoff)
    if inst_maj > cut_maj or (inst_maj == cut_maj and inst_min > cut_min):
        print(f"  - {lib}: installed {installed}, training covers ~{cutoff}.x")
PY
)
    if [ -n "$py_warnings" ]; then
      while IFS= read -r w; do
        [ -n "$w" ] && WARNINGS+=("$w")
      done <<< "$py_warnings"
    fi
  fi
fi

# Node.js: read package.json directly (fast)
if [ -f "package.json" ] && command -v node &>/dev/null; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    pkg=$(echo "$line" | awk '{print $1}')
    cutoff=$(echo "$line" | awk '{print $2}')
    pkg_version=$(node -e "
try {
  const p = require('./package.json');
  const v = p.dependencies?.['$pkg'] || p.devDependencies?.['$pkg'] || '';
  console.log(v.replace(/[^\d.]/g, ''));
} catch(e) {}
" 2>/dev/null)
    if [ -n "$pkg_version" ]; then
      if [ "$(version_exceeds_cutoff "$pkg_version" "$cutoff")" = "gap" ]; then
        WARNINGS+=("  - ${pkg} (node): installed ${pkg_version}, training covers ~${cutoff}.x")
      fi
    fi
  done <<< "$NODE_CUTOFFS"
fi

# ---------------------------------------------------------------------------
# Output — only when warnings exist
# ---------------------------------------------------------------------------

if [ ${#WARNINGS[@]} -gt 0 ]; then
  echo ""
  echo "STALENESS WARNING (staleness-guard):"
  for w in "${WARNINGS[@]}"; do
    echo "$w"
  done
  echo ""
  echo "  Architectural claims about these libraries should be verified"
  echo "  against current docs. Run /architecture-check before making"
  echo "  design decisions involving these dependencies."
  echo ""
fi

exit 0
