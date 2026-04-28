#!/usr/bin/env bash
# tests/test_scanner.sh: regression tests for staleness-scan.py
# Run from any directory; uses absolute path to scanner.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCAN="python3 $ROOT/bin/staleness-scan.py"

PASS=0
FAIL=0

assert_finding_count() {
  local label="$1"
  local expected="$2"
  local input="$3"

  local actual
  actual=$(echo "$input" | $SCAN 2>&1 | grep -cE "^STALENESS RISK" || true)

  if [ "$actual" -eq "$expected" ]; then
    printf "  \033[1;32mPASS\033[0m  %-50s expected=%d got=%d\n" "$label" "$expected" "$actual"
    PASS=$((PASS + 1))
  else
    printf "  \033[1;31mFAIL\033[0m  %-50s expected=%d got=%d\n" "$label" "$expected" "$actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_exit_code() {
  local label="$1"
  local expected_rc="$2"
  local input="$3"

  echo "$input" | $SCAN > /dev/null 2>&1
  local actual_rc=$?

  if [ "$actual_rc" -eq "$expected_rc" ]; then
    printf "  \033[1;32mPASS\033[0m  %-50s rc=%d\n" "$label" "$actual_rc"
    PASS=$((PASS + 1))
  else
    printf "  \033[1;31mFAIL\033[0m  %-50s expected_rc=%d got=%d\n" "$label" "$expected_rc" "$actual_rc"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== staleness-scan.py regression tests ==="
echo

# Canonical Spark example: 4 HIGH-risk findings
CANONICAL="Apache Spark Structured Streaming uses micro-batches and cannot achieve sub-second latency. Use Flink instead of Spark because Spark cannot do continuous processing."
assert_finding_count "canonical Spark example fires 4 findings" 4 "$CANONICAL"
assert_exit_code "canonical example exits 1 (HIGH risk)" 1 "$CANONICAL"

# Empty / whitespace input: no findings, exit 0
assert_finding_count "empty input fires 0 findings" 0 ""
assert_exit_code "empty input exits 0" 0 ""

# Lines without library names: no findings even with cannot/uses
NO_LIB="The schema cannot be modified once frozen.
This approach cannot scale beyond a single node.
The legacy code is not designed for our use case.
The migration cannot proceed until the lock is released."
assert_finding_count "no-library prose: 0 findings" 0 "$NO_LIB"
assert_exit_code "no-library prose exits 0" 0 "$NO_LIB"

# Library mentioned but not in a claim shape
NEUTRAL="We're using Spark for our pipeline.
The Spark migration is scheduled for Q3.
Read the Spark documentation before deploying."
assert_finding_count "neutral library mentions: 0 findings" 0 "$NEUTRAL"

# Comparative quality claim
COMPARATIVE="PostgreSQL is better than MySQL for OLAP workloads."
assert_finding_count "comparative quality fires 1 finding" 1 "$COMPARATIVE"

# Capability absence with library
ABSENCE="Pandas cannot handle datasets larger than memory."
assert_finding_count "capability absence with library: 1 finding" 1 "$ABSENCE"

# Code blocks should be skipped
CODE_BLOCK='Here is an example:
\`\`\`python
spark.read.parquet("path")
\`\`\`
Done.'
assert_finding_count "code blocks not scanned" 0 "$CODE_BLOCK"

echo
echo "=== summary: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] || exit 1
exit 0
