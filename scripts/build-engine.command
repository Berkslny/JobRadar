#!/bin/bash
# Packs the Python engine (engine/) into the wheel the app carries (JobRadar/jobradar-<version>-py3-none-any.whl).
# Run this after changing anything under engine/, then build the app again.
set -euo pipefail
cd "$(dirname "$0")/.."

UV="$(command -v uv || true)"
if [ -z "$UV" ] && [ -x "$HOME/Library/Application Support/JobRadar/runtime/bin/uv" ]; then
  UV="$HOME/Library/Application Support/JobRadar/runtime/bin/uv"
fi

OUT=$(mktemp -d)
if [ -n "$UV" ]; then
  "$UV" build --wheel --out-dir "$OUT" engine
else
  python3 -m pip wheel engine --no-deps -w "$OUT"
fi
rm -f JobRadar/jobradar-*.whl
cp "$OUT"/jobradar-*.whl JobRadar/
rm -rf "$OUT" engine/build engine/src/*.egg-info
echo "Done: $(ls JobRadar/jobradar-*.whl)"
