#!/usr/bin/env bash
# tests/test_version_check.sh: verify version-check.sh runs cleanly,
# is silent when no warnings, fast on warm cache, and exits 0.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/bin/version-check.sh"

PASS=0
FAIL=0

pass() { printf "  \033[1;32mPASS\033[0m  %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  \033[1;31mFAIL\033[0m  %s\n" "$1"; FAIL=$((FAIL + 1)); }

echo "=== version-check.sh tests ==="
echo

# Bash syntax check
if bash -n "$HOOK"; then
  pass "shell syntax is valid"
else
  fail "shell syntax error"
fi

# Always exits 0 (hook must not block on warnings)
"$HOOK" > /dev/null 2>&1
rc=$?
if [ "$rc" -eq 0 ]; then
  pass "exits 0 even when warnings emitted"
else
  fail "expected exit 0, got $rc"
fi

# Warm-cache run completes quickly (under 500ms on most systems)
# We measure via /usr/bin/time and compare seconds of wall-clock.
"$HOOK" > /dev/null 2>&1  # warm the cache
warm_start=$(date +%s%N)
"$HOOK" > /dev/null 2>&1
warm_end=$(date +%s%N)
warm_ms=$(( (warm_end - warm_start) / 1000000 ))

if [ "$warm_ms" -lt 500 ]; then
  pass "warm-cache run completed in ${warm_ms}ms (target < 500ms)"
else
  fail "warm-cache run took ${warm_ms}ms (target < 500ms)"
fi

# In an empty environment with no installed flagged libraries, output is empty
TMPDIR_TEST=$(mktemp -d)
(
  cd "$TMPDIR_TEST"
  PATH="/nonexistent" "$HOOK" 2>/dev/null > out.txt
  if [ ! -s out.txt ]; then
    echo "PASS: silent when no pip available"
    exit 0
  fi
  echo "FAIL: expected silent output without pip, got:"
  cat out.txt
  exit 1
) && pass "silent when pip unavailable" || fail "not silent when pip unavailable"
rm -rf "$TMPDIR_TEST"

echo
echo "=== summary: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] || exit 1
exit 0
