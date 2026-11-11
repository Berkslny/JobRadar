#!/bin/bash
# Builds JobRadar (Release) and packs it into dist/JobRadar-<version>.dmg.
# Double-click this file in Finder (or run it in Terminal). Needs Xcode, but no Apple developer account.
#
# How the app in the disk image is signed:
#   - With a "Developer ID Application" certificate when one is installed (or named in JOBRADAR_SIGN_IDENTITY),
#     and notarised when JOBRADAR_NOTARY_PROFILE names a keychain profile made with
#     `xcrun notarytool store-credentials`. Such a download opens without a warning.
#   - Otherwise with a local ("ad hoc") signature, which names nobody. Other Macs then ask once before
#     they open the app (see README).
# A development certificate ("Apple Development: …") is never used: it does not remove that warning, and it
# would put the name of the developer's Apple account into every copy.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="JobRadar.xcodeproj"
# Build outside the project folder: in a folder that iCloud Drive syncs (Documents, Desktop), macOS adds
# attributes to files that make code signing fail.
WORK=$(mktemp -d "${TMPDIR:-/tmp}/jobradar-build.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
BUILD="$WORK/build"
APP="$BUILD/Release/JobRadar.app"

if ! ls JobRadar/*.whl >/dev/null 2>&1; then
  echo "The engine package (JobRadar/jobradar-*.whl) is missing. Run scripts/build-engine.command first."
  exit 1
fi

# xcodebuild needs the full Xcode. On many Macs the command line points at the small "Command Line Tools"
# instead, so look for Xcode itself and use it for this run only.
if ! xcodebuild -version >/dev/null 2>&1; then
  for candidate in "/Applications/Xcode.app" "/Applications/Xcode-beta.app" "$HOME/Applications/Xcode.app" \
                   "$(mdfind "kMDItemCFBundleIdentifier == 'com.apple.dt.Xcode'" 2>/dev/null | head -1)"; do
    if [ -n "$candidate" ] && [ -d "$candidate/Contents/Developer" ]; then
      export DEVELOPER_DIR="$candidate/Contents/Developer"
      break
    fi
  done
fi
if ! xcodebuild -version >/dev/null 2>&1; then
  echo "Xcode was not found. Install Xcode from the App Store, open it once, and try again."
  exit 1
fi

echo "Building JobRadar (Release). This takes a few minutes…"
LOG="$WORK/build.log"
# Signing happens below, so the build itself needs no account, team or certificate.
if ! xcodebuild -project "$PROJECT" -target JobRadar -configuration Release -quiet \
     SYMROOT="$BUILD" OBJROOT="$WORK/obj" CODE_SIGNING_ALLOWED=NO build >"$LOG" 2>&1; then
  echo "The build failed. The last lines of its report:"
  tail -n 25 "$LOG"
  exit 1
fi
[ -d "$APP" ] || { echo "The build product was not found: $APP"; exit 1; }
VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")
BINARY="$APP/Contents/MacOS/$(/usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "$APP/Contents/Info.plist")"

# Take out the debugging records. They are not needed to run the app, and they hold the folder paths
# (with the user name) of the Mac that built it.
if ! xcrun strip -S "$BINARY" 2>"$WORK/strip.log"; then
  echo "Removing the debugging records did not work:"
  tail -n 5 "$WORK/strip.log"
  exit 1
fi
if grep -q -a -F "$PWD/" "$BINARY"; then
  echo "Note: the app still contains the path of this folder ($PWD)."
fi
xattr -cr "$APP" 2>/dev/null || true

IDENTITY="${JOBRADAR_SIGN_IDENTITY:-}"
if [ -z "$IDENTITY" ]; then
  IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null \
    | sed -n 's/.*"\(Developer ID Application: [^"]*\)".*/\1/p' | head -1)
fi
if [ -n "$IDENTITY" ]; then
  echo "Signing with: $IDENTITY"
  codesign --force --options runtime --timestamp --sign "$IDENTITY" "$APP"
else
  echo "No Developer ID certificate found: the app gets a local signature."
  echo "Other Macs will ask once before they open it (see README)."
  codesign --force --options runtime --sign - "$APP"
fi
codesign --verify --strict "$APP"

STAGE="$WORK/stage"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/JobRadar.app"
ln -s /Applications "$STAGE/Applications"
DMG="$WORK/JobRadar-$VERSION.dmg"
hdiutil create -volname "JobRadar" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

if [ -n "$IDENTITY" ]; then
  codesign --force --timestamp --sign "$IDENTITY" "$DMG"
  if [ -n "${JOBRADAR_NOTARY_PROFILE:-}" ]; then
    echo "Sending the disk image to Apple for notarisation…"
    xcrun notarytool submit "$DMG" --keychain-profile "$JOBRADAR_NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
  else
    echo "Not notarised: set JOBRADAR_NOTARY_PROFILE to notarise (see README)."
  fi
fi

mkdir -p dist
FINAL="dist/JobRadar-$VERSION.dmg"
rm -f "$FINAL"
cp "$DMG" "$FINAL"
echo "Done: $PWD/$FINAL"
# JOBRADAR_NO_REVEAL: set by the app, which shows the result itself
[ -n "${JOBRADAR_NO_REVEAL:-}" ] || open -R "$FINAL"
