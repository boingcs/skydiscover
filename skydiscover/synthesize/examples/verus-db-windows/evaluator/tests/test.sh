#!/usr/bin/env bash
# SkySynth's formal-proof suite: correctness is the only score.
set -uo pipefail
cd "$(dirname "$0")"
: "${SKYDISCOVER_IMPL:?set SKYDISCOVER_IMPL to the candidate directory}"
: "${SKYDISCOVER_INTERFACE:?set SKYDISCOVER_INTERFACE to the immutable spec directory}"

python_cmd="${SKYDISCOVER_PYTHON:-}"
if [ -z "$python_cmd" ]; then
  if command -v python3 >/dev/null 2>&1; then
    python_cmd=python3
  else
    python_cmd=python
  fi
fi

tests=("$@")
[ ${#tests[@]} -eq 0 ] && tests=(proof.py)
rc=0
for test in "${tests[@]}"; do
  [ "$test" = "test.sh" ] && continue
  if "$python_cmd" "$test"; then
    echo "PASS $test"
  else
    echo "FAIL $test"
    rc=1
  fi
done
exit $rc
