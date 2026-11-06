# VeilMark releases

This folder is published automatically by GitHub Actions (`.github/workflows/build-windows.yml`):
whenever a new version (from `veilmark/__init__.py`) lands on the default branch and passes every
test, the Windows build, a smoke test of the built app and a test install, the workflow puts here:

* `VeilMark-Setup.exe` — the newest installer (always the same file name)
* `latest.json` — version, size and SHA-256 checksum of that installer

Installed copies of VeilMark read `latest.json`, download the installer in the background, verify
its checksum and offer **Update ready – click to install**.

**Download the latest version:**
https://raw.githubusercontent.com/AhmedWalid4499/My-Encryption-app/HEAD/releases/VeilMark-Setup.exe

Do not edit these files by hand.
