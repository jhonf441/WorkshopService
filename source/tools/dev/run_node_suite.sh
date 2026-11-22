#!/bin/sh
# Runs every tests/*.test.js, one node process each (in parallel, 4 at a time), and prints the failing ones. Usage: sh tools/dev/run_node_suite.sh [dir]
cd "${1:-$(dirname "$0")/../..}" || exit 1
ls tests/*.test.js | xargs -P 4 -I{} sh -c 'timeout 300 node {} >/dev/null 2>&1 || echo "FAIL {}"'
echo done
