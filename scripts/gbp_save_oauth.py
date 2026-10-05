#!/usr/bin/env python3
"""Save Google Business Profile OAuth client values locally. Never prints secrets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GBP_FILE = ROOT / ".mds" / "gbp-oauth.json"
GSC_FILE = ROOT / ".mds" / "gsc-oauth.json"


def main() -> int:
    data = {}
    if GBP_FILE.exists():
        loaded = json.loads(GBP_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded

    reused = False
    if GSC_FILE.exists():
        gsc = json.loads(GSC_FILE.read_text(encoding="utf-8"))
        if isinstance(gsc, dict) and gsc.get("client_id") and gsc.get("client_secret"):
            data["client_id"] = gsc["client_id"]
            data["client_secret"] = gsc["client_secret"]
            data["application_type"] = str(gsc.get("application_type") or "desktop")
            reused = True

    if not reused:
        if not sys.stdin.isatty():
            print(
                "No Search Console OAuth file found. Run this in an interactive terminal:\n"
                "  python3 scripts/gbp_save_oauth.py",
                file=sys.stderr,
            )
            return 2
        print("Paste values from Google Cloud → APIs & Services → Credentials.")
        client_id = input("Client ID: ").strip()
        client_secret = input("Client secret: ").strip()
        app_type = (
            input("Application type [desktop/web] (default desktop): ").strip() or "desktop"
        ).lower()
        if not client_id.endswith(".apps.googleusercontent.com"):
            print("That does not look like a Google Client ID.", file=sys.stderr)
            return 1
        if len(client_secret) < 15:
            print("Client secret looks too short.", file=sys.stderr)
            return 1
        if app_type not in {"desktop", "web"}:
            print("Application type must be desktop or web.", file=sys.stderr)
            return 1
        data["client_id"] = client_id
        data["client_secret"] = client_secret
        data["application_type"] = app_type

    GBP_FILE.parent.mkdir(parents=True, exist_ok=True)
    GBP_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if reused:
        print("Saved to .mds/gbp-oauth.json using the existing Search Console client.")
    else:
        print("Saved to .mds/gbp-oauth.json")
    print("Next: python3 scripts/gbp_connect.py login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
