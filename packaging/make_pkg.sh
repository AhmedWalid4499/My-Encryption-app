#!/bin/bash
# Build the Mac installer wizard (a .pkg that opens in Apple's Installer app) from dist/VeilMark.app.
# Run on a Mac after PyInstaller (and after make_dmg.sh, which signs the app):
#   bash packaging/make_pkg.sh      -> dist/VeilMark-macOS-<AppleSilicon|Intel>-Installer.pkg
set -euo pipefail
cd "$(dirname "$0")/.."

APP=dist/VeilMark.app
HERE=packaging/macos-installer
[ -d "$APP" ] || { echo "Build the app first: pyinstaller packaging/veilmark-macos.spec"; exit 1; }

VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")
case "$(lipo -archs "$APP/Contents/MacOS/VeilMark")" in
  arm64) ARCH=arm64; LABEL=AppleSilicon; ARCHNAME="Apple silicon" ;;
  x86_64) ARCH=x86_64; LABEL=Intel; ARCHNAME="Intel" ;;
  *) echo "Unexpected processor type(s) in $APP"; exit 1 ;;
esac
OUT="dist/VeilMark-macOS-$LABEL-Installer.pkg"

# make sure the app carries a valid (ad hoc) signature, whether or not make_dmg.sh ran first
codesign --verify --deep --strict "$APP" 2>/dev/null || codesign --force --deep --sign - "$APP"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/root" "$WORK/resources" "$WORK/packages"
ditto "$APP" "$WORK/root/VeilMark.app"

# Always install into /Applications (never "relocate" to wherever an old copy happens to be), and replace an
# existing VeilMark.app as a whole.
pkgbuild --analyze --root "$WORK/root" "$WORK/component.plist" >/dev/null
plutil -replace 0.BundleIsRelocatable -bool NO "$WORK/component.plist"
plutil -replace 0.BundleOverwriteAction -string upgrade "$WORK/component.plist"

pkgbuild --root "$WORK/root" --component-plist "$WORK/component.plist" --install-location /Applications \
  --scripts "$HERE/scripts" --identifier com.ahmedwalid.veilmark --version "$VERSION" \
  "$WORK/packages/VeilMark-component.pkg" >/dev/null

# Wizard pages, with the VeilMark shield in the bottom-left corner of every page.
cp "$HERE/resources/"*.html "$WORK/resources/"
sips -Z 150 assets/veilmark.png --out "$WORK/resources/background.png" >/dev/null
sed -e "s/@VERSION@/$VERSION/g" -e "s/@ARCH@/$ARCH/g" -e "s/@ARCHNAME@/$ARCHNAME/g" \
  "$HERE/distribution.xml" > "$WORK/distribution.xml"

rm -f "$OUT"
productbuild --distribution "$WORK/distribution.xml" --resources "$WORK/resources" \
  --package-path "$WORK/packages" --version "$VERSION" "$OUT" >/dev/null
echo "Installer:  $OUT"
