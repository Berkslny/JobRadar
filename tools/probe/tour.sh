#!/bin/bash
# Runs the app on the Mac runner with a made-up workspace and walks through the new screens.
set -uo pipefail
OUT="$RUNNER_TEMP/out"
mkdir -p "$OUT"
exec > >(tee "$OUT/tour.log") 2>&1
HERE="$(cd "$(dirname "$0")" && pwd)"
BUNDLE=com.berkselenay.JobRadar
SUPPORT="$HOME/Library/Application Support/JobRadar"
PORT=8790
N=0

section() { echo; echo "=== $* ($(date +%H:%M:%S)) ==="; }
ui() { osascript "$HERE/ui.applescript" "$@" 2>&1; }
key() { osascript -e "tell application \"System Events\" to $1" 2>&1; }

shot() {
  N=$((N + 1))
  local base
  base=$(printf "%s/%02d-%s" "$OUT" "$N" "$1")
  screencapture -x "$base.png"
  "$RUNNER_TEMP/winlist" JobRadar | while IFS=$'\t' read -r id layer x y w h name; do
    [ "$layer" = "0" ] || continue
    screencapture -x -o -l "$id" "$base-w${w}x${h}.png" 2>/dev/null || true
  done
  echo "shot $base"
}

dump() { ui dump > "$OUT/tree-$1.txt"; echo "tree-$1: $(wc -l < "$OUT/tree-$1.txt") lines"; }

wait_text() {
  local needle="$1" limit="$2" start=$SECONDS r
  while [ $((SECONDS - start)) -lt "$limit" ]; do
    r=$(ui has "$needle")
    case "$r" in yes*) echo "found after $((SECONDS - start)) s: ${r:0:300}"; return 0 ;; esac
    sleep 3
  done
  echo "NOT FOUND within $limit s: $needle"
  return 1
}

engine_pid() { lsof -nP -t -iTCP:$PORT -sTCP:LISTEN 2>/dev/null | head -1; }

wait_engine() {
  for i in $(seq 1 "$1"); do
    if [ -n "$(engine_pid)" ]; then echo "engine listening after about $((i * 2)) s"; return 0; fi
    sleep 2
  done
  echo "ENGINE NOT UP"; tail -n 30 "$SUPPORT/logs/engine.log" 2>/dev/null
  return 1
}

api() {  # api PATH FILE
  local pid token
  pid=$(engine_pid)
  token=$(ps eww -p "$pid" | tr ' ' '\n' | sed -n 's/^JOBRADAR_API_TOKEN=//p' | head -1)
  curl -s -H "Authorization: Bearer $token" "http://127.0.0.1:$PORT/api/v1/$1" > "$OUT/$2"
  echo "$2: $(wc -c < "$OUT/$2") bytes"
}

quit_app() {
  osascript -e 'tell application "JobRadar" to quit' 2>&1 || true
  for i in $(seq 1 20); do pgrep -x JobRadar >/dev/null || break; sleep 1; done
  pgrep -x JobRadar >/dev/null && { echo "app still running, killing it"; pkill -x JobRadar; sleep 2; }
  pgrep -lf "jobradar serve" || echo "engine stopped"
}

section "tools and display"
swiftc -O "$HERE/winlist.swift" -o "$RUNNER_TEMP/winlist" 2>&1 | tail -3
swiftc -O "$HERE/modes.swift" -o "$RUNNER_TEMP/modes" 2>&1 | tail -3
"$RUNNER_TEMP/modes"
for size in "1920 1080" "1680 1050" "1600 900" "1440 900" "1280 800"; do
  # shellcheck disable=SC2086
  if "$RUNNER_TEMP/modes" set $size; then break; fi
done
sleep 2
"$RUNNER_TEMP/modes" | tail -1
defaults write com.apple.dock autohide -bool true && killall Dock
sleep 2

section "build"
if ! xcodebuild -project JobRadar.xcodeproj -target JobRadar -configuration Debug \
    SYMROOT="$RUNNER_TEMP/build" OBJROOT="$RUNNER_TEMP/obj" CODE_SIGNING_ALLOWED=NO \
    ARCHS=arm64 ONLY_ACTIVE_ARCH=NO build > "$RUNNER_TEMP/build.log" 2>&1; then
  tail -n 40 "$RUNNER_TEMP/build.log"
  exit 1
fi
tail -n 2 "$RUNNER_TEMP/build.log"
APP="$RUNNER_TEMP/build/Debug/JobRadar.app"

section "first start: the app installs its engine"
defaults write $BUNDLE onboardingDone -bool true
defaults write $BUNDLE autoScan -bool false
defaults write $BUNDLE notificationsEnabled -bool false
defaults write $BUNDLE settingsTab -string matching
open -n "$APP"
wait_engine 120
for i in $(seq 1 60); do
  grep -q '"job_boards" : true' "$SUPPORT/runtime/installed.json" 2>/dev/null && { echo "job boards added"; break; }
  sleep 3
done
shot first-start-empty
quit_app

section "made-up workspace"
JOBRADAR_LANG=en "$SUPPORT/runtime/venv/bin/python" "$HERE/seed.py" "$SUPPORT/workspace" 2>&1 | grep -v Warning | head -30

section "second start"
open -n "$APP"
wait_engine 60
sleep 6
osascript -e 'tell application "JobRadar" to activate' 2>&1
sleep 2
ui windows
"$RUNNER_TEMP/winlist" JobRadar
shot inbox
dump inbox
api "summary" summary-before.json
api "bench" bench-before.json
api "matching" matching-before.json

section "a posting"
ui click AXStaticText "Junior FPGA Developer – Radar Signal Processing"
sleep 4
shot posting
dump posting

section "status page"
ui click AXStaticText "Status and sources"
wait_text "How well JobRadar finds your jobs" 30
shot status-top
dump status
ui scroll 0.5
sleep 2
shot status-middle
ui scroll 1.0
sleep 2
shot status-bottom

section "judging sheet"
ui press AXButton "Judge jobs…"
wait_text "Does this job fit you?" 20
sleep 2
shot judge-1
dump judge
key 'keystroke "1"'
sleep 2
shot judge-after-key-1
key 'keystroke "3"'
sleep 2
shot judge-after-key-3
ui press AXButton "Maybe"
sleep 2
ui press AXButton "Cannot tell"
sleep 2
shot judge-after-buttons
ui has "judged ·"
ui press AXButton "Done"
sleep 3
shot status-after-judging
api "bench" bench-after-judging.json

section "settings: matching"
key 'keystroke "," using command down'
sleep 4
ui windows
shot matching-off
dump matching-off
ui press AXCheckBox "Use smart matching"
sleep 5
shot matching-turning-on
wait_text "The model works" 420 || { ui has "could not"; ui has "did not"; ui has "Error"; }
shot matching-on
dump matching-on
cat "$SUPPORT/runtime/installed.json"
ui press AXButton "Compare my jobs now"
sleep 3
shot matching-comparing
wait_text "jobs compared" 420 || { ui has "did not work"; }
shot matching-compared
dump matching-compared
api "matching" matching-after.json
key 'keystroke "w" using command down'
sleep 2

section "after matching"
ui click AXStaticText "Status and sources"
sleep 1
key 'keystroke "r" using command down'
sleep 5
ui scroll 0.5
sleep 2
shot status-with-matching-middle
ui scroll 1.0
sleep 2
shot status-with-matching-bottom
dump status-with-matching
api "bench" bench-after-matching.json
api "summary" summary-after.json
api "jobs?view=inbox&limit=100" jobs-inbox.json

section "engine log"
cp "$SUPPORT/logs/engine.log" "$OUT/engine.log" 2>/dev/null
tail -n 30 "$OUT/engine.log"
quit_app
echo "tour finished"
