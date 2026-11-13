#!/bin/bash
# The Intel half of the app, run through Rosetta on the Apple Silicon runner: does the engine install,
# and do the matching package and its model work in an x86_64 Python?
LOG_NAME=intel
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

prepare_tools

section "Rosetta"
if ! arch -x86_64 /usr/bin/true 2>/dev/null; then
  softwareupdate --install-rosetta --agree-to-license 2>&1 | tail -2
fi
arch -x86_64 /usr/bin/true && echo "x86_64 programs run here"
sysctl -n machdep.cpu.brand_string
arch -x86_64 sysctl -n hw.optional.avx2_0 2>/dev/null | sed 's/^/avx2 for x86_64 programs: /'

section "install from the disk image and start the Intel half"
install_from "$(ls "$RUNNER_TEMP"/dmg/JobRadar-*.dmg | tail -1)" || exit 1
app_defaults
export OPEN_ARGS="--arch x86_64"
open -n --arch x86_64 "$APP"
wait_engine 240
sleep 4
lsappinfo info -only arch -app JobRadar 2>&1 | head -2
file "$SUPPORT/runtime/bin/uv" | sed 's/.*: //'
file -L "$SUPPORT/runtime/venv/bin/python" | sed 's/.*: //'
"$SUPPORT/runtime/venv/bin/python" -c "import platform, jobradar; print('engine', jobradar.__version__, 'on', platform.machine(), platform.python_version())"
wait_job_boards
quit_app

section "made-up workspace"
JOBRADAR_LANG=en "$SUPPORT/runtime/venv/bin/python" "$HERE/seed.py" "$SUPPORT/workspace" 2>&1 | grep -v Warning | sed -n 3,4p

section "smart matching in the Intel half"
start_app 90
shot intel-inbox
key 'keystroke "," using command down'
sleep 5
ax press AXCheckBox "$(L "Use smart matching")" | tail -1
wait_text "$(Lpart "The model works: %@ answered in %@ seconds." 1)" 600 || { ax texts | tail -30; cat "$SUPPORT/runtime/installed.json"; }
shot intel-matching-on
"$SUPPORT/runtime/venv/bin/python" -c "import onnxruntime, fastembed, platform; print('onnxruntime', onnxruntime.__version__, 'fastembed', fastembed.__version__, platform.machine())" 2>&1 | grep -v Warning | tail -1
reveal AXButton "$(L "Compare my jobs now")" "$(L "Matching")"
ax press AXButton "$(L "Compare my jobs now")" | tail -1
wait_text "$(Lpart "%@ jobs compared, %@ let through." 2)" 600 || ax texts | tail -30
shot intel-matching-compared
api "matching" matching-intel.json
python3 -c "import json, sys; m = json.load(open(sys.argv[1])); print('scored', m['scored'], 'promoted', m['promoted'], 'threshold', m['threshold'], 'last error:', m['last_error'] or '-')" "$OUT/matching-intel.json"
key 'keystroke "w" using command down'
sleep 1
sidebar "$(L "Status and sources")" "$(L "Version")"
sleep 2
shot intel-status
cp "$SUPPORT/logs/engine.log" "$OUT/engine-intel.log" 2>/dev/null
quit_app
echo "intel walk finished"
