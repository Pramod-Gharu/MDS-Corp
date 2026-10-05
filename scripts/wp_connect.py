#!/usr/bin/env python3
"""Talk to the live WordPress site. Credentials stay in a local gitignored file."""

from __future__ import annotations

import argparse
import base64
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LOCAL_FILE = ROOT / ".mds" / "wp.json"


class ConnectError(RuntimeError):
    pass


def load_local() -> Dict[str, str]:
    if not LOCAL_FILE.exists():
        raise ConnectError("Local connection file is missing.")
    try:
        data = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConnectError("Local connection file is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ConnectError("Local connection file must be a JSON object.")
    site = str(data.get("site") or "").strip().rstrip("/")
    user = str(data.get("user") or "").strip()
    secret = str(data.get("secret") or "").strip()
    if not site:
        raise ConnectError("Local connection file is missing the site URL.")
    return {"site": site, "user": user, "secret": secret}


def _request(
    url: str,
    auth: Optional[Tuple[str, str]] = None,
    timeout: int = 20,
) -> Tuple[int, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "MDS-Corp-local-connector",
    }
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except urllib.error.URLError as exc:
        raise ConnectError("Could not reach the site.") from exc
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"ok": False}
    return status, payload


def public_status(site: str) -> Dict[str, Any]:
    code, payload = _request(f"{site}/wp-json/")
    if code != 200 or not isinstance(payload, dict):
        return {"ok": False, "http": code}
    return {
        "ok": True,
        "http": code,
        "name": payload.get("name"),
        "home": payload.get("home") or payload.get("url"),
    }


def auth_status(site: str, user: str, secret: str) -> Dict[str, Any]:
    if not user or not secret:
        return {"ok": False, "reason": "incomplete"}
    code, payload = _request(f"{site}/wp-json/wp/v2/users/me", auth=(user, secret))
    if code == 200 and isinstance(payload, dict) and payload.get("id"):
        return {
            "ok": True,
            "http": code,
            "id": payload.get("id"),
            "slug": payload.get("slug"),
        }
    return {"ok": False, "http": code}


def cmd_status(_: argparse.Namespace) -> int:
    cfg = load_local()
    public = public_status(cfg["site"])
    print(f"site\t{cfg['site']}")
    print(f"public\t{'ok' if public.get('ok') else 'fail'}\t{public.get('name') or ''}")
    auth = auth_status(cfg["site"], cfg["user"], cfg["secret"])
    if auth.get("ok"):
        print(f"auth\tok\tid={auth.get('id')}")
        return 0
    if auth.get("reason") == "incomplete":
        print("auth\tmissing")
        return 2
    print(f"auth\tfail\thttp={auth.get('http')}")
    return 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local WordPress connection (secrets never printed).")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="Check public and authenticated access")
    status.set_defaults(func=cmd_status)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except ConnectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
