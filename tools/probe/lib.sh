# Shared by the walks through the app on the Mac runner (sourced, not run).
set -uo pipefail
OUT="$RUNNER_TEMP/out"
mkdir -p "$OUT"
exec > >(tee "$OUT/${LOG_NAME:-run}.log") 2>&1
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUNDLE=com.berkselenay.JobRadar
SUPPORT="$HOME/Library/Application Support/JobRadar"
PORT=8790
N=0
LANG_NOW=en

section() { echo; echo "=== $* ($(date +%H:%M:%S)) ==="; }
ax() { "$RUNNER_TEMP/ax" "$@" 2>&1; }
key() { osascript -e "tell application \"System Events\" to $1" 2>&1; }

# The text of the interface in the language the app shows now.
L() {
  if [ "$LANG_NOW" = "tr" ]; then
    python3 -c "import sys; sys.path.insert(0, '$ROOT/tools'); from tr_table import TR; print(TR.get(sys.argv[1], sys.argv[1]))" "$1"
  else
    printf '%s\n' "$1"
  fi
}
# The N-th piece (from 1) of a text with %@ placeholders, without the spaces around it.
Lpart() {
  L "$1" | python3 -c "import sys, re; parts = [p.strip() for p in re.split(r'%(?:\d\\$)?@', sys.stdin.read().strip())]; print(parts[int(sys.argv[1]) - 1])" "$2"
}

shot() {
  N=$((N + 1))
  local base
  base=$(printf "%s/%02d-%s" "$OUT" "$N" "$1")
  "$RUNNER_TEMP/winlist" JobRadar | while IFS=$'\t' read -r id layer x y w h name; do
    [ "$layer" = "0" ] || continue
    [ "$w" -ge 300 ] || continue
    screencapture -x -o -l "$id" "$base-w${w}x${h}.png" 2>/dev/null || true
  done
  echo "shot $(basename "$base")"
}

screen() {
  N=$((N + 1))
  screencapture -x "$(printf "%s/%02d-%s-screen.png" "$OUT" "$N" "$1")"
  echo "screen $1"
}

wait_text() {
  local needle="$1" limit="$2" start=$SECONDS r
  while [ $((SECONDS - start)) -lt "$limit" ]; do
    if r=$(ax has "$needle"); then echo "found after $((SECONDS - start)) s: ${r:0:300}"; return 0; fi
    sleep 2
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
  echo "$2: $(wc -c < "$OUT/$2" | tr -d ' ') bytes"
}

start_app() {
  open -n "$APP"
  wait_engine "$1"
  sleep 6
  osascript -e 'tell application "JobRadar" to activate' 2>&1
  sleep 2
  ax windows
}

quit_app() {
  osascript -e 'tell application "JobRadar" to quit' 2>&1 || true
  for i in $(seq 1 20); do pgrep -x JobRadar >/dev/null || break; sleep 1; done
  pgrep -x JobRadar >/dev/null && { echo "app still running, killing it"; pkill -x JobRadar; sleep 2; }
  pgrep -lf "jobradar serve" || echo "engine stopped"
}

sidebar() {  # sidebar LABEL TEXT-ON-THAT-PAGE
  ax click AXStaticText "$1" | tail -1
  sleep 2
  if [ -n "${2:-}" ] && ! ax has "$2" >/dev/null; then
    echo "the click did not open the page; selecting the row instead"
    ax select "$1"
    sleep 2
  fi
  ax windows | head -2
}

# Scrolls a window step by step until the element exists, then brings it into view.
reveal() {  # reveal ROLE LABEL [WINDOW]
  local f
  for f in 0 0.15 0.3 0.45 0.6 0.75 0.9 1; do
    if ax show "$1" "$2" >/dev/null; then echo "revealed: $2"; return 0; fi
    ax scroll "$f" ${3:+"$3"} >/dev/null
    sleep 1
  done
  ax show "$1" "$2" >/dev/null && { echo "revealed: $2"; return 0; }
  echo "NOT REVEALED: $2"
  return 1
}

page_shots() {  # page_shots NAME [WINDOW]: the page at five scroll positions
  local f
  for f in 0 0.25 0.5 0.75 1; do
    ax scroll "$f" ${2:+"$2"} >/dev/null
    sleep 1
    shot "$1-$f"
  done
}

promoted_job() {  # prints "id<TAB>title" of a posting smart matching let through
  api "jobs?view=all" jobs-all-$LANG_NOW.json >/dev/null
  python3 - "$OUT/jobs-all-$LANG_NOW.json" "$(L "Semantic match")" <<'EOF'
import json, sys
jobs = json.load(open(sys.argv[1]))["jobs"]
names = {sys.argv[2], "Semantic match", "Anlamsal eşleşme"}
hits = [j for j in jobs if any(b.get("label") in names for b in j.get("badges", []))]
print("promoted postings: %d" % len(hits), file=sys.stderr)
for j in hits:
    print("  %s · %s · quick %.0f · status %s" % (j["title"], j["company"], j["prescore"], j["status"]), file=sys.stderr)
if hits:
    print(hits[0]["id"] + "\t" + hits[0]["title"])
EOF
}


# Compiles the helper tools, enlarges the screen, hides the Dock.
prepare_tools() {
  section "tools and display"
  if ! swiftc -swift-version 5 -O "$HERE/ax.swift" -o "$RUNNER_TEMP/ax" 2> "$OUT/ax-build.txt"; then
    cat "$OUT/ax-build.txt"
    exit 1
  fi
  swiftc -O "$HERE/winlist.swift" -o "$RUNNER_TEMP/winlist" 2>&1 | tail -3
  swiftc -O "$HERE/modes.swift" -o "$RUNNER_TEMP/modes" 2>&1 | tail -3
  "$RUNNER_TEMP/modes" set 1920 1080 || "$RUNNER_TEMP/modes" set 1680 1050 || "$RUNNER_TEMP/modes" set 1440 900
  sleep 2
  "$RUNNER_TEMP/modes" | tail -1
  defaults write com.apple.dock autohide -bool true && killall Dock
  sleep 2
}

# Copies JobRadar out of a disk image into /Applications, the way a user installs it.
install_from() {  # install_from DMG
  local mount
  mount=$(hdiutil attach -nobrowse -readonly "$1" | awk -F'\t' '/\/Volumes\// {print $NF}' | tail -1)
  [ -d "$mount/JobRadar.app" ] || { echo "NO APP IN $1 (mounted at: $mount)"; return 1; }
  rm -rf /Applications/JobRadar.app
  ditto "$mount/JobRadar.app" /Applications/JobRadar.app
  hdiutil detach "$mount" -quiet || true
  APP=/Applications/JobRadar.app
  echo "installed $(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist") from $(basename "$1")"
  codesign --verify --strict "$APP" && echo "signature valid"
}

app_defaults() {
  defaults write $BUNDLE onboardingDone -bool true
  defaults write $BUNDLE autoScan -bool false
  defaults write $BUNDLE notificationsEnabled -bool false
  defaults write $BUNDLE settingsTab -string matching
}

wait_job_boards() {
  for i in $(seq 1 60); do
    grep -q '"job_boards" : true' "$SUPPORT/runtime/installed.json" 2>/dev/null && { echo "job boards added"; return 0; }
    sleep 3
  done
  echo "JOB BOARDS NOT ADDED"
}
