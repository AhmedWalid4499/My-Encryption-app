"""The watermark key built into VeilMark.

Every copy of the app shares this key, so any VeilMark can read (and create) VeilMark
watermarks - there is no key to manage in Settings. Do NOT change it: files watermarked
with it could no longer be read. Older per-computer "team keys" (VeilMark 1.0-1.3) are
still tried when extracting, so files made with those keep working.
"""

APP_KEY = "BPIKQAPXE5DHVZXA6C5H2QYA6EPBSEAESG6MYHBXAZSFZPIQ"
