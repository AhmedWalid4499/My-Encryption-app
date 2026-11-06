#!/bin/bash
# Wrap dist/VeilMark.app into a drag-to-Applications disk image (run on a Mac, after PyInstaller).
# Usage: bash packaging/make_dmg.sh            -> dist/VeilMark-macOS-AppleSilicon.dmg (or -Intel.dmg)
set -euo pipefail
cd "$(dirname "$0")/.."

APP=dist/VeilMark.app
[ -d "$APP" ] || { echo "Build the app first: pyinstaller packaging/veilmark-macos.spec"; exit 1; }

case "$(file -b "$APP/Contents/MacOS/VeilMark")" in
  *arm64*) ARCH=AppleSilicon ;;
  *x86_64*) ARCH=Intel ;;
  *) echo "Unknown processor type of $APP"; exit 1 ;;
esac
OUT="dist/VeilMark-macOS-$ARCH.dmg"

# The app isn't signed with a paid Apple Developer ID, so sign it "ad hoc": Apple silicon Macs refuse to run
# completely unsigned apps, and a consistent signature over the whole bundle avoids "app is damaged" errors.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
ditto "$APP" "$STAGE/VeilMark.app"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/How to open VeilMark.txt" <<'TXT'
Installing VeilMark on your Mac
===============================

1. Drag VeilMark onto the Applications folder in this window.
2. Open your Applications folder and double-click VeilMark.

The first time only, macOS may say it "cannot verify" VeilMark, because the app isn't
registered with Apple (that costs a yearly fee). It is safe to open:

  * Click "Done" (not "Move to Trash").
  * Open System Settings -> Privacy & Security, scroll down, and click "Open Anyway"
    next to the message about VeilMark. Confirm with your password or Touch ID.

  (On macOS 14 or older you can instead right-click VeilMark -> Open -> Open.)

After that VeilMark opens normally, and later updates install themselves.
TXT

rm -f "$OUT"
hdiutil create -volname "VeilMark" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$OUT" >/dev/null
echo "Disk image: $OUT"
