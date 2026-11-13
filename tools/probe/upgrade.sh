#!/bin/bash
# The way an existing user gets the new version: JobRadar 1.0 with data, then the new app over it.
LOG_NAME=upgrade
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

DB="$SUPPORT/workspace/data/jobradar.db"
counts() { sqlite3 "$DB" "select status, count(*) from jobs group by status order by status" | tr '\n' ' '; echo; }
tables() { sqlite3 "$DB" "select name from sqlite_master where type = 'table' order by name" | tr '\n' ' '; echo; }

prepare_tools

section "1.0: install and first start"
OLD=$(ls downloads/JobRadar-1.0.dmg 2>/dev/null || ls "$RUNNER_TEMP"/old/JobRadar-1.0.dmg)
install_from "$OLD" || exit 1
app_defaults
open -n "$APP"
wait_engine 120
wait_job_boards
api "summary" summary-10-empty.json
python3 -c "import json, sys; d = json.load(open(sys.argv[1])); print('engine', d['version'], 'features', d.get('features'))" "$OUT/summary-10-empty.json"
quit_app
cp "$SUPPORT/runtime/installed.json" "$OUT/installed-10.json"

section "1.0: a workspace with jobs, made by the 1.0 engine"
JOBRADAR_LANG=en "$SUPPORT/runtime/venv/bin/python" "$HERE/seed.py" "$SUPPORT/workspace" 2>&1 | grep -v Warning | head -8
"$SUPPORT/runtime/venv/bin/python" -c "import jobradar; print('seeded with engine', jobradar.__version__)"
tables
counts > "$OUT/counts-10.txt"; cat "$OUT/counts-10.txt"

section "1.0: the app with that data"
start_app 60
shot v10-inbox
api "summary" summary-10.json
api "jobs?view=all" jobs-10.json
# something the user did in 1.0: shortlist a posting, so there is a status change to carry over
FIRST=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['jobs'][0]['id'])" "$OUT/jobs-10.json")
echo "first posting: $FIRST"
quit_app

section "1.1: install over it"
install_from "$(ls "$RUNNER_TEMP"/dmg/JobRadar-*.dmg | tail -1)" || exit 1
START=$SECONDS
open -n "$APP"
wait_engine 150
echo "engine up $((SECONDS - START)) s after opening the new version"
sleep 6
osascript -e 'tell application "JobRadar" to activate' 2>&1
sleep 2
ax windows
cat "$SUPPORT/runtime/installed.json"; echo
cp "$SUPPORT/runtime/installed.json" "$OUT/installed-11.json"
shot v11-inbox
api "summary" summary-11.json
api "jobs?view=all" jobs-11.json
api "bench" bench-11.json
api "matching" matching-11.json
tables
counts > "$OUT/counts-11.txt"; cat "$OUT/counts-11.txt"
python3 - "$OUT" <<'EOF'
import json, sys
out = sys.argv[1]
old, new = (json.load(open(f"{out}/summary-{v}.json")) for v in ("10", "11"))
print("engine", old["version"], "->", new["version"], "· features", new.get("features"))
print("counts equal:", old["counts"] == new["counts"], "· views equal:", old["views"] == new["views"])
a, b = (json.load(open(f"{out}/jobs-{v}.json"))["jobs"] for v in ("10", "11"))
key = lambda j: (j["id"], j["status"], j["prescore"], j["llm_score"])
print("postings:", len(a), "->", len(b), "· same ids, statuses and scores:", sorted(map(key, a)) == sorted(map(key, b)))
bench = json.load(open(f"{out}/bench-11.json"))
print("bench labels:", bench["labels"], "· groups:", [(g["id"], g["postings"]) for g in bench["gate"]["groups"]])
m = json.load(open(f"{out}/matching-11.json"))
print("matching enabled:", m["enabled"], "· installed:", m["installed"], "· scored:", m["scored"])
EOF
diff "$OUT/counts-10.txt" "$OUT/counts-11.txt" && echo "the database holds the same postings"

section "1.1: the new screens work on the old data"
sidebar "$(L "Status and sources")" "$(L "Version")"
wait_text "$(L "How well JobRadar finds your jobs")" 30
shot v11-status
reveal AXButton "$(L "Judge jobs…")"
ax press AXButton "$(L "Judge jobs…")" | tail -1
wait_text "$(L "Does this job fit you?")" 20
key 'keystroke "1"'
sleep 2
key 'keystroke "3"'
sleep 2
shot v11-judge
ax has "$(Lpart "%@ judged · %@ to go" 2)"
ax press AXButton "$(L "Done")" | tail -1
sleep 2
key 'keystroke "," using command down'
sleep 4
ax press AXCheckBox "$(L "Use smart matching")" | tail -1
wait_text "$(Lpart "The model works: %@ answered in %@ seconds." 1)" 420 || ax texts | tail -25
cat "$SUPPORT/runtime/installed.json"; echo
reveal AXButton "$(L "Compare my jobs now")" "$(L "Matching")"
ax press AXButton "$(L "Compare my jobs now")" | tail -1
wait_text "$(Lpart "%@ jobs compared, %@ let through." 2)" 420 || ax texts | tail -25
shot v11-matching
api "matching" matching-11-after.json
python3 -c "import json, sys; m = json.load(open(sys.argv[1])); print('scored', m['scored'], 'promoted', m['promoted'], 'threshold', m['threshold'])" "$OUT/matching-11-after.json"
key 'keystroke "w" using command down'
sleep 1

section "end"
cp "$SUPPORT/logs/engine.log" "$OUT/engine-upgrade.log" 2>/dev/null
grep -n -i "traceback\|error" "$OUT/engine-upgrade.log" | head -10 || true
quit_app
echo "upgrade walk finished"
