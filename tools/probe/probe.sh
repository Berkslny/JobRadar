#!/bin/bash
# First look at the Mac runner: is there a screen, may scripts drive other apps, does the app start.
set -uo pipefail
OUT="$RUNNER_TEMP/out"
mkdir -p "$OUT"
exec > >(tee "$OUT/probe.log") 2>&1

section() { echo; echo "=== $* ==="; }

section "system"
sw_vers
sysctl -n machdep.cpu.brand_string hw.ncpu hw.memsize
whoami; echo "HOME=$HOME"
launchctl managername || true
defaults read -g AppleLanguages 2>/dev/null || true
defaults read -g AppleLocale 2>/dev/null || true
xcodebuild -version
csrutil status || true
system_profiler SPDisplaysDataType 2>/dev/null | head -40 || true

section "privacy database"
sqlite3 "$HOME/Library/Application Support/com.apple.TCC/TCC.db" \
  'select service, client, client_type, auth_value from access' 2>&1 | head -80 || true
sudo sqlite3 "/Library/Application Support/com.apple.TCC/TCC.db" \
  'select service, client, client_type, auth_value from access' 2>&1 | head -80 || true

section "screen and scripting before the app"
screencapture -x "$OUT/00-desktop.png"; echo "screencapture exit $?"
sips -g pixelWidth -g pixelHeight "$OUT/00-desktop.png" 2>/dev/null | tail -2 || true
osascript -e 'tell application "System Events" to get name of every process whose background only is false' 2>&1 || true
osascript -e 'tell application "System Events" to get UI elements enabled' 2>&1 || true

section "build"
set -o pipefail
if ! xcodebuild -project JobRadar.xcodeproj -target JobRadar -configuration Debug \
    SYMROOT="$RUNNER_TEMP/build" OBJROOT="$RUNNER_TEMP/obj" CODE_SIGNING_ALLOWED=NO \
    ARCHS=arm64 ONLY_ACTIVE_ARCH=NO build > "$RUNNER_TEMP/build.log" 2>&1; then
  tail -n 40 "$RUNNER_TEMP/build.log"
  exit 1
fi
tail -n 3 "$RUNNER_TEMP/build.log"
APP="$RUNNER_TEMP/build/Debug/JobRadar.app"
ls -la "$APP/Contents/MacOS" "$APP/Contents/Resources" | head -30
codesign -dv "$APP" 2>&1 | head -8 || true

section "first launch"
open -n "$APP"; echo "open exit $?"
sleep 20
pgrep -lf JobRadar || true
screencapture -x "$OUT/01-after-20s.png"
osascript -e 'tell application "System Events" to tell process "JobRadar" to get {name, position, size} of every window' 2>&1 || true

section "engine install"
SUPPORT="$HOME/Library/Application Support/JobRadar"
for i in $(seq 1 60); do
  if [ -f "$SUPPORT/runtime/installed.json" ] && lsof -nP -iTCP:8790 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "engine up after about $((i * 5)) s"; break
  fi
  sleep 5
done
cat "$SUPPORT/runtime/installed.json" 2>/dev/null || echo "no marker"
ls -la "$SUPPORT" "$SUPPORT/workspace" 2>/dev/null | head -30
tail -n 20 "$SUPPORT/logs/engine.log" 2>/dev/null || true
screencapture -x "$OUT/02-engine-up.png"

section "accessibility tree"
osascript -e 'tell application "JobRadar" to activate' 2>&1 || true
sleep 1
osascript -e 'tell application "System Events" to tell process "JobRadar" to get entire contents of window 1' \
  > "$OUT/tree-main.txt" 2>&1 || true
wc -c "$OUT/tree-main.txt"; head -c 1500 "$OUT/tree-main.txt"; echo

section "open settings with the keyboard"
osascript -e 'tell application "System Events" to keystroke "," using command down' 2>&1 || true
sleep 3
screencapture -x "$OUT/03-settings.png"
osascript -e 'tell application "System Events" to tell process "JobRadar" to get {name, position, size} of every window' 2>&1 || true
osascript -e 'tell application "System Events" to tell process "JobRadar" to get entire contents of window 1' \
  > "$OUT/tree-settings.txt" 2>&1 || true
wc -c "$OUT/tree-settings.txt"; head -c 1500 "$OUT/tree-settings.txt"; echo

section "engine token visible to scripts"
PID=$(lsof -nP -t -iTCP:8790 -sTCP:LISTEN | head -1)
echo "engine pid: $PID"
if [ -n "$PID" ]; then
  ps eww -p "$PID" | tr ' ' '\n' | grep -c '^JOBRADAR_API_TOKEN=' || true
fi

section "done"
osascript -e 'tell application "JobRadar" to quit' 2>&1 || true
sleep 3
pgrep -lf "jobradar serve" || echo "engine stopped"
