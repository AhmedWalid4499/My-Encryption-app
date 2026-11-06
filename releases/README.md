# VeilMark releases

Every released version of VeilMark is here as its own installer:

* `VeilMark-Setup-<version>.exe`: the Windows installer for that version, e.g. `VeilMark-Setup-1.4.0.exe`
* `VeilMark-macOS-AppleSilicon-Installer-<version>.pkg` / `VeilMark-macOS-Intel-Installer-<version>.pkg`: the Mac
  installation wizards (recommended for installing by hand)
* `VeilMark-macOS-AppleSilicon-<version>.dmg` / `VeilMark-macOS-Intel-<version>.dmg`: the Mac disk images (drag and
  drop; the app also updates itself from these)
* `latest.json`: which Windows version is newest, plus the size and SHA-256 checksum of its installer
* `latest-macos-arm64.json` / `latest-macos-x86_64.json`: the same for the Apple silicon and Intel Mac apps

**How the app updates itself:** installed copies of VeilMark read `latest.json` when they start (and every
6 hours). (on a Mac: its `latest-macos-*.json`). If it names a newer version, the app downloads that `.exe` or `.dmg` from this folder in the background,
checks its SHA-256 checksum, and shows **"Update ready – click to install"**.

**To install VeilMark:** open the newest `VeilMark-Setup-<version>.exe` (Windows) or
`VeilMark-macOS-<AppleSilicon|Intel>-Installer-<version>.pkg` (Mac) above and click **Download**
(the "⋯" or download button on GitHub's file page).

These files are added automatically by GitHub Actions (`.github/workflows/build-windows.yml`) when a
higher version number reaches the default branch and passes every test, a smoke test of each built app and
a test install. Do not edit them by hand.
