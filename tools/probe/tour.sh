#!/bin/bash
# Installs the app from the disk image and walks through the new screens with a made-up workspace,
# first in English (turning smart matching on for real), then in Turkish.
LOG_NAME=tour
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

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

prepare_tools

section "install from the disk image"
install_from "$NEW_DMG" || exit 1

section "first start: the app installs its engine"
app_defaults
open -n "$APP"
wait_engine 120
ax trusted
if ! ax windows | grep -q AXWindow; then
  echo "THE ACCESSIBILITY TOOL SEES NO WINDOW"
  ax windows
  quit_app
  exit 1
fi
wait_job_boards
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
