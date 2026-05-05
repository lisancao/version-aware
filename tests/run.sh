#!/usr/bin/env bash
# tests/run.sh: run all version-aware tests
set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
RC=0

echo
"$DIR/test_scanner.sh" || RC=$?
echo
"$DIR/test_version_check.sh" || RC=$?
echo

if [ "$RC" -eq 0 ]; then
  echo "ALL TESTS PASSED"
else
  echo "SOME TESTS FAILED (rc=$RC)"
fi

exit $RC
