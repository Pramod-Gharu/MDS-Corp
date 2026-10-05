#!/usr/bin/env python3
"""Prompt for GSC OAuth client values and save them locally. Never prints secrets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_FILE = ROOT / ".mds" / "gsc-oauth.json"


def main() -> int:
    if not sys.stdin.isatty():
        print(
            "Run this in an interactive terminal:\n"
            "  python3 scripts/gsc_save_oauth.py",
            file=sys.stderr,
        )
        return 2

    data = {}
    if LOCAL_FILE.exists():
        data = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}

    print("Paste values from Google Cloud → APIs & Services → Credentials.")
    print("You can paste into both prompts. The secret will be visible while typing.")
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

    data.update(
        {
            "site_url": str(data.get("site_url") or "sc-domain:mdsindustrialcorp.com"),
            "client_id": client_id,
            "client_secret": client_secret,
            "application_type": app_type,
        }
    )
    LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("Saved to .mds/gsc-oauth.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
