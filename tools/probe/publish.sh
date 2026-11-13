#!/bin/bash
# Pushes the probe's output folder to a branch of its own, so it can be fetched with git.
set -uo pipefail
OUT="$RUNNER_TEMP/out"
mkdir -p "$OUT"
cd "$OUT"
rm -rf .git
git init -q
git checkout -q -b out
git add -A
git -c user.name="probe" -c user.email="probe@users.noreply.github.com" commit -q -m "Probe output of run $GITHUB_RUN_ID" || true
BRANCH="probe-out/${GITHUB_REF_NAME#probe/}${1:+-$1}"
git push -q -f "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" "out:refs/heads/$BRANCH"
echo "pushed to $BRANCH"
ls -la "$OUT" | head -60
