# VeilMark releases

Every released version of VeilMark is here as its own Windows installer:

* `VeilMark-Setup-<version>.exe`: the installer for that version, e.g. `VeilMark-Setup-1.4.0.exe`
* `latest.json`: which version is newest, plus the size and SHA-256 checksum of its installer

**How the app updates itself:** installed copies of VeilMark read `latest.json` when they start (and every
6 hours). If it names a newer version, the app downloads that `.exe` from this folder in the background,
checks its SHA-256 checksum, and shows **"Update ready – click to install"**.

**To install VeilMark:** open the newest `VeilMark-Setup-<version>.exe` above and click **Download**
(the "⋯" or download button on GitHub's file page).

These files are added automatically by GitHub Actions (`.github/workflows/build-windows.yml`) when a
higher version number reaches the default branch and passes every test, a smoke test of the built app and
a test install. Do not edit them by hand.
