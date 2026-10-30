#!/bin/sh
# Git pre-push hook: runs the fast tests of this repo and refuses the push if any fails. NOT installed by anything.
# Install (once, by the owner):   cp tools/pre-push.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push
# Skip once (use with care):      git push --no-verify
# Every dsf/test_*.py module runs on its own (one discover run hangs); each has 90 s. Takes a few minutes.
set -u
ROOT="$(git rev-parse --show-toplevel)"
export PYTHONDONTWRITEBYTECODE=1
fail=0

run() {
  # run <dir> <module>
  if ! (cd "$1" && timeout 90 python -m unittest "$2" >/dev/null 2>&1); then
    echo "pre-push: FAILED $1/$2" >&2
    fail=1
  fi
}

for f in "$ROOT"/dsf/test_*.py; do
  run "$ROOT/dsf" "$(basename "$f" .py)"
done
for f in "$ROOT"/bridge/tests/test_*.py; do
  run "$ROOT/bridge/tests" "$(basename "$f" .py)"
done
(cd "$ROOT/dsf" && python published_texts.py >/dev/null 2>&1 && cd "$ROOT" && git diff --quiet -- dwc-src/i18n) || { echo "pre-push: published texts are out of date (python dsf/published_texts.py)" >&2; fail=1; }
if command -v node >/dev/null 2>&1; then
  for t in render vue-templates-compile vue-i18n-syntax; do
    (cd "$ROOT" && node "tests/$t.test.js" >/dev/null 2>&1) || { echo "pre-push: FAILED tests/$t.test.js" >&2; fail=1; }
  done
fi

if [ "$fail" -ne 0 ]; then
  echo "pre-push: push refused, fix the tests above" >&2
  exit 1
fi
echo "pre-push: all fast tests passed"
