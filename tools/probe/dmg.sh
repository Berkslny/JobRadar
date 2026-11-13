#!/bin/bash
# Builds the disk image with the repository's own script and looks at what came out.
set -uo pipefail
OUT="$RUNNER_TEMP/out"
mkdir -p "$OUT"
exec > >(tee "$OUT/dmg.log") 2>&1

section() { echo; echo "=== $* ($(date +%H:%M:%S)) ==="; }

look() {  # look DMG: what is inside a disk image and how it is signed
  local dmg="$1" mount app
  echo "--- $(basename "$dmg")"
  ls -l "$dmg" | awk '{print $5 " bytes"}'
  shasum -a 256 "$dmg" | awk '{print "sha256 " $1}'
  hdiutil verify -quiet "$dmg" && echo "image verifies"
  codesign -dv "$dmg" 2>&1 | head -3
  mount=$(hdiutil attach -nobrowse -readonly "$dmg" | awk -F'\t' '/\/Volumes\// {print $NF}' | tail -1)
  app="$mount/JobRadar.app"
  ls "$mount"
  echo "version $(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist")" \
       "build $(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$app/Contents/Info.plist")" \
       "needs macOS $(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$app/Contents/Info.plist")"
  echo "architectures: $(lipo -archs "$app/Contents/MacOS/JobRadar")"
  ls "$app/Contents/Resources" | tr '\n' ' '; echo
  codesign -dvv "$app" 2>&1 | grep -E "Identifier|Format|CodeDirectory|Signature|Authority|TeamIdentifier|Runtime|Sealed" | head -12
  codesign --verify --deep --strict "$app" && echo "signature valid (deep, strict)"
  spctl -a -t exec -vv "$app" 2>&1 | head -3
  echo "paths of the build machine left in the app: $(grep -a -c "/Users/" "$app/Contents/MacOS/JobRadar" || true) lines"
  hdiutil detach "$mount" -quiet || true
}

section "system"
sw_vers | tr '\n' ' '; echo
xcodebuild -version | tr '\n' ' '; echo
security find-identity -v -p codesigning 2>&1 | tail -2

section "build the disk image (scripts/make-dmg.command)"
JOBRADAR_NO_REVEAL=1 bash scripts/make-dmg.command || { echo "MAKE-DMG FAILED"; exit 1; }
DMG=$(ls dist/JobRadar-*.dmg | tail -1)
mkdir -p "$RUNNER_TEMP/dmg"
cp "$DMG" "$RUNNER_TEMP/dmg/"
cp "$DMG" "$OUT/"

section "the new disk image"
look "$DMG"

section "for comparison: the 1.0 disk image of the repository"
if [ -f downloads/JobRadar-1.0.dmg ]; then look downloads/JobRadar-1.0.dmg; else echo "not in this branch"; fi

section "the engine package inside the new app"
MOUNT=$(hdiutil attach -nobrowse -readonly "$DMG" | awk -F'\t' '/\/Volumes\// {print $NF}' | tail -1)
shasum -a 256 "$MOUNT/JobRadar.app/Contents/Resources/"jobradar-*.whl JobRadar/jobradar-*.whl
hdiutil detach "$MOUNT" -quiet || true
echo "done"
