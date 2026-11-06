# VeilMark releases

This folder is published automatically by GitHub Actions (`.github/workflows/build-windows.yml`):
whenever a new version (from `veilmark/__init__.py`) lands on the default branch and passes every
test, the Windows and Mac builds, a smoke test of each built app and a test install, the workflow puts here:

* `VeilMark-Setup.exe` — the newest Windows installer (always the same file name)
* `latest.json` — version, size and SHA-256 checksum of that installer
* `VeilMark-macOS-AppleSilicon.dmg` / `VeilMark-macOS-Intel.dmg` — the newest Mac disk images
* `latest-macos-arm64.json` / `latest-macos-x86_64.json` — their version, size and SHA-256 checksum

Installed copies of VeilMark read `latest.json`, download the installer in the background, verify
its checksum and offer **Update ready – click to install**.

**Download the latest version:**
* Windows: https://raw.githubusercontent.com/AhmedWalid4499/My-Encryption-app/HEAD/releases/VeilMark-Setup.exe
* Mac (Apple silicon): https://raw.githubusercontent.com/AhmedWalid4499/My-Encryption-app/HEAD/releases/VeilMark-macOS-AppleSilicon.dmg
* Mac (Intel): https://raw.githubusercontent.com/AhmedWalid4499/My-Encryption-app/HEAD/releases/VeilMark-macOS-Intel.dmg

Do not edit these files by hand.
