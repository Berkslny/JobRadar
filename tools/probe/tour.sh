#!/bin/bash
# Runs the app on the Mac runner with a made-up workspace and walks through the new screens,
# first in English (turning smart matching on for real), then in Turkish.
set -uo pipefail
OUT="$RUNNER_TEMP/out"
mkdir -p "$OUT"
exec > >(tee "$OUT/tour.log") 2>&1
HERE="$(cd "$(dirname "$0")" && pwd)"
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

status_page() {
  section "$LANG_NOW: status page"
  sidebar "$(L "Status and sources")" "$(L "Version")"
  wait_text "$(L "How well JobRadar finds your jobs")" 30
  page_shots "$LANG_NOW-status$1"
  ax texts > "$OUT/texts-$LANG_NOW-status$1.txt"
  wc -l < "$OUT/texts-$LANG_NOW-status$1.txt"
  # the same page in a roomy window
  ax resize 1500 940
  sleep 2
  ax scroll 0 >/dev/null; sleep 1; shot "$LANG_NOW-status$1-wide-0"
  ax scroll 1 >/dev/null; sleep 1; shot "$LANG_NOW-status$1-wide-1"
  ax resize 1080 732
  sleep 2
  ax scroll 0 >/dev/null
}

judging_sheet() {  # judging_sheet full|look
  section "$LANG_NOW: judging sheet"
  reveal AXButton "$(L "Judge jobs…")"
  ax press AXButton "$(L "Judge jobs…")" | tail -1
  wait_text "$(L "Does this job fit you?")" 20
  sleep 2
  shot "$LANG_NOW-judge-1"
  ax texts > "$OUT/texts-$LANG_NOW-judge.txt"
  if [ "$1" = "full" ]; then
    key 'keystroke "1"'
    sleep 2
    shot "$LANG_NOW-judge-after-key-1"
    key 'keystroke "3"'
    sleep 2
    ax press AXButton "$(L "Maybe")" | tail -1
    sleep 2
    ax press AXButton "$(L "Cannot tell")" | tail -1
    sleep 2
    shot "$LANG_NOW-judge-after-four"
    ax has "$(Lpart "%@ judged · %@ to go" 2)"
  fi
  ax press AXButton "$(L "Done")" | tail -1
  sleep 3
}

posting() {  # posting full|look
  section "$LANG_NOW: a posting smart matching let through"
  local line id
  line=$(promoted_job)
  id="${line%%$'\t'*}"
  if [ -z "$id" ]; then
    echo "NO PROMOTED POSTING; opening the first posting of the list instead"
    id=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['jobs'][0]['id'])" "$OUT/jobs-all-$LANG_NOW.json")
    line="$id"
  fi
  echo "opening $line"
  open "jobradar://job/$id"
  sleep 5
  ax windows | head -2
  ax has "$(Lpart "Semantic score %@" 1)"
  shot "$LANG_NOW-posting"
  ax texts > "$OUT/texts-$LANG_NOW-posting.txt"
  ax press AXMenuButton "$(L "My verdict")" | tail -1 || ax press AXPopUpButton "$(L "My verdict")" | tail -1 \
    || ax press AXButton "$(L "My verdict")" | tail -1
  sleep 2
  screen "$LANG_NOW-verdict-menu"
  ax dump > "$OUT/tree-$LANG_NOW-posting-menu.txt"
  if [ "$1" = "full" ]; then
    ax press AXMenuItem "$(L "Fits")" | tail -1
    sleep 3
    ax has "$(Lpart "Your verdict: %@" 1)"
    shot "$LANG_NOW-posting-judged"
  else
    key 'key code 53'
    sleep 1
  fi
}

section "tools and display"
if ! swiftc -swift-version 5 -O "$HERE/ax.swift" -o "$RUNNER_TEMP/ax" 2> "$OUT/ax-build.txt"; then
  cat "$OUT/ax-build.txt"
  exit 1
fi
grep -c warning "$OUT/ax-build.txt" || true
swiftc -O "$HERE/winlist.swift" -o "$RUNNER_TEMP/winlist" 2>&1 | tail -3
swiftc -O "$HERE/modes.swift" -o "$RUNNER_TEMP/modes" 2>&1 | tail -3
"$RUNNER_TEMP/modes" set 1920 1080 || "$RUNNER_TEMP/modes" set 1680 1050 || "$RUNNER_TEMP/modes" set 1440 900
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
ax trusted
if ! ax windows | grep -q AXWindow; then
  echo "THE ACCESSIBILITY TOOL SEES NO WINDOW"
  ax windows
  quit_app
  exit 1
fi
for i in $(seq 1 60); do
  grep -q '"job_boards" : true' "$SUPPORT/runtime/installed.json" 2>/dev/null && { echo "job boards added"; break; }
  sleep 3
done
quit_app

section "made-up workspace"
JOBRADAR_LANG=en "$SUPPORT/runtime/venv/bin/python" "$HERE/seed.py" "$SUPPORT/workspace" 2>&1 | grep -v Warning | head -12

# ------------------------------------------------------------------------------------------------ English
section "en: start"
start_app 60
shot en-inbox
api "bench" bench-before.json

status_page "-before"
judging_sheet full
shot en-status-after-judging
api "bench" bench-after-judging.json

section "en: settings, smart matching off"
key 'keystroke "," using command down'
sleep 4
ax windows
page_shots en-matching-off "$(L "Matching")"
ax dump > "$OUT/tree-en-matching-off.txt"

section "en: turning smart matching on"
ax scroll 0 "$(L "Matching")" >/dev/null
ax press AXCheckBox "$(L "Use smart matching")" | tail -1
sleep 3
shot en-matching-turning-on
wait_text "$(Lpart "The model works: %@ answered in %@ seconds." 1)" 420 || ax texts | tail -25
page_shots en-matching-on "$(L "Matching")"
cat "$SUPPORT/runtime/installed.json"; echo

section "en: comparing the jobs"
reveal AXButton "$(L "Compare my jobs now")" "$(L "Matching")"
ax press AXButton "$(L "Compare my jobs now")" | tail -1
sleep 2
shot en-matching-comparing
wait_text "$(Lpart "%@ jobs compared, %@ let through." 2)" 420 || ax texts | tail -25
page_shots en-matching-compared "$(L "Matching")"
ax texts > "$OUT/texts-en-matching.txt"
api "matching" matching-after.json
sqlite3 -separator ' | ' "$SUPPORT/workspace/data/jobradar.db" \
  "select printf('%.3f', m.semantic), printf('%.3f', m.track_sim), printf('%.3f', m.profile_sim), m.best_track, m.promoted, j.status, cast(j.prescore as int), coalesce(l.label, '-'), j.title, coalesce(j.filtered_reason, '') from job_match m join jobs j on j.id = m.job_id left join labels l on l.job_id = j.id order by m.semantic desc" \
  > "$OUT/semantic-scores.txt"
wc -l < "$OUT/semantic-scores.txt"
key 'keystroke "w" using command down'
sleep 2

section "en: inbox after matching"
sidebar "$(L "Inbox")" ""
key 'keystroke "r" using command down'
sleep 4
shot en-inbox-after-matching
ax has "$(L "Semantic match")"
posting full
status_page "-after"
api "bench" bench-after-matching.json
api "summary" summary-after.json
cp "$SUPPORT/logs/engine.log" "$OUT/engine-en.log" 2>/dev/null
quit_app

# ------------------------------------------------------------------------------------------------ Turkish
section "tr: start"
LANG_NOW=tr
defaults write $BUNDLE appLanguage -string tr
defaults write $BUNDLE AppleLanguages -array tr
start_app 60
shot tr-inbox
status_page ""
judging_sheet look

section "tr: settings"
key 'keystroke "," using command down'
sleep 4
ax windows
page_shots tr-matching "$(L "Matching")"
ax texts > "$OUT/texts-tr-matching.txt"
key 'keystroke "w" using command down'
sleep 2
posting look
api "bench" bench-tr.json

section "end"
cp "$SUPPORT/logs/engine.log" "$OUT/engine-tr.log" 2>/dev/null
tail -n 15 "$OUT/engine-tr.log"
quit_app
echo "tour finished"
