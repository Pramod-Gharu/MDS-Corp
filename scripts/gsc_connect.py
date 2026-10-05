#!/usr/bin/env python3
"""Talk to Google Search Console. Credentials stay in a local gitignored file."""

from __future__ import annotations

import argparse
import json
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LOCAL_FILE = ROOT / ".mds" / "gsc-oauth.json"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
USER_AGENT = "MDS-Corp-gsc-connector"
SSL_CONTEXT = ssl.create_default_context()


class ConnectError(RuntimeError):
    pass


def load_local() -> Dict[str, Any]:
    if not LOCAL_FILE.exists():
        raise ConnectError("Local GSC connection file is missing.")
    try:
        data = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConnectError("Local GSC connection file is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ConnectError("Local GSC connection file must be a JSON object.")
    client_id = str(data.get("client_id") or "").strip()
    client_secret = str(data.get("client_secret") or "").strip()
    site_url = str(data.get("site_url") or "").strip()
    if not client_id or not client_secret:
        raise ConnectError("Local GSC file is missing client_id or client_secret.")
    if not site_url:
        raise ConnectError("Local GSC file is missing site_url.")
    data["client_id"] = client_id
    data["client_secret"] = client_secret
    data["site_url"] = site_url
    data["application_type"] = str(data.get("application_type") or "desktop").strip().lower()
    return data


def save_local(data: Dict[str, Any]) -> None:
    LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
    timeout: int = 30,
) -> Tuple[int, Any, str]:
    req_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except urllib.error.URLError as exc:
        raise ConnectError("Could not reach Google.") from exc
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"ok": False, "raw": "non-json"}
    return status, payload, raw


def exchange_code(cfg: Dict[str, Any], code: str, redirect_uri: str) -> Dict[str, Any]:
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    status, payload, _ = _request(
        TOKEN_URL,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body,
    )
    if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
        google_error = ""
        if isinstance(payload, dict):
            google_error = str(payload.get("error") or "")
            detail = str(payload.get("error_description") or "").strip()
            if google_error and detail:
                google_error = f"{google_error}: {detail}"
            elif detail:
                google_error = detail
        hint = "Google login failed."
        if google_error:
            hint = f"Google login failed ({google_error})."
        if str(payload.get("error") or "") == "invalid_client":
            hint += " Recheck the Client ID and Client secret in .mds/gsc-oauth.json against Cloud Console."
        elif status != 200:
            hint += " Confirm the OAuth consent screen test user and try login again."
        raise ConnectError(hint)
    return payload


def refresh_access_token(cfg: Dict[str, Any]) -> str:
    refresh_token = str(cfg.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ConnectError("Not logged in yet. Run: python3 scripts/gsc_connect.py login")
    body = urllib.parse.urlencode(
        {
            "refresh_token": refresh_token,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    status, payload, _ = _request(
        TOKEN_URL,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body,
    )
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if status != 200 or not token:
        raise ConnectError("Could not refresh Google access. Run login again.")
    new_refresh = str(payload.get("refresh_token") or "").strip()
    if new_refresh:
        cfg["refresh_token"] = new_refresh
        save_local(cfg)
    return str(token)


def auth_request(cfg: Dict[str, Any], url: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
    token = refresh_access_token(cfg)
    body = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    status, data, _ = _request(url, method=method, headers=headers, body=body)
    return status, data


def open_in_chrome(url: str) -> None:
    """Prefer Google Chrome so login uses the already signed-in GSC account."""
    try:
        subprocess.run(["open", "-a", "Google Chrome", url], check=True)
        print("Opened Google Chrome.")
        return
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    opened = webbrowser.open(url, new=1, autoraise=True)
    if opened:
        print("Opened the default browser (Chrome was not found).")
        return
    raise ConnectError("Could not open Google Chrome.")


def wait_for_code(redirect_host: str, port: int, open_browser) -> Tuple[str, str]:
    result: Dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if query.get("code"):
                result["code"] = query["code"][0]
                body = b"<html><body><p>Google login complete. You can close this tab.</p></body></html>"
                self.send_response(200)
            else:
                result["error"] = query.get("error", ["missing_code"])[0]
                body = b"<html><body><p>Google login did not finish. You can close this tab.</p></body></html>"
                self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = HTTPServer((redirect_host, port), Handler)
    try:
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        open_browser()
        thread.join(timeout=180)
    finally:
        server.server_close()
    if not result.get("code"):
        raise ConnectError(result.get("error") or "Timed out waiting for Google login.")
    redirect_uri = f"http://{redirect_host}:{port}/"
    return result["code"], redirect_uri


def cmd_login(_: argparse.Namespace) -> int:
    cfg = load_local()
    host = "127.0.0.1"
    port = 8080
    redirect_uri = f"http://{host}:{port}/"
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print("Google Chrome should open a permission page.")
    print("In Chrome, choose the Search Console account if asked, then click Allow.")

    def open_browser() -> None:
        open_in_chrome(url)

    code, used_redirect = wait_for_code(host, port, open_browser)
    tokens = exchange_code(cfg, code, used_redirect)
    refresh = str(tokens.get("refresh_token") or "").strip()
    if not refresh:
        raise ConnectError("Google did not return a refresh token. Run login again and click Allow.")
    cfg["refresh_token"] = refresh
    save_local(cfg)
    print("login\tok")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    cfg = load_local()
    if not str(cfg.get("refresh_token") or "").strip():
        print("auth\tmissing")
        print("Run: python3 scripts/gsc_connect.py login")
        return 2
    status, payload = auth_request(cfg, SITES_URL)
    if status != 200 or not isinstance(payload, dict):
        print(f"auth\tfail\thttp={status}")
        return 3
    entries = payload.get("siteEntry") or []
    wanted = cfg["site_url"]
    matches = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        site = str(item.get("siteUrl") or "")
        matches.append(site)
        if site == wanted:
            print("auth\tok")
            print(f"property\tok\t{wanted}")
            return 0
    print("auth\tok")
    print(f"property\tmissing\t{wanted}")
    print(f"properties_seen\t{len(matches)}")
    return 4


def coverage_line(result: Dict[str, Any]) -> str:
    index_status = result.get("indexStatusResult") or {}
    verdict = index_status.get("verdict") or "unknown"
    coverage = index_status.get("coverageState") or index_status.get("indexingState") or ""
    crawled = index_status.get("lastCrawlTime") or ""
    bits = [str(verdict)]
    if coverage:
        bits.append(str(coverage))
    if crawled:
        bits.append(f"last_crawl={crawled}")
    return "\t".join(bits)


def inspect_url(cfg: Dict[str, Any], inspection_url: str) -> Tuple[int, Dict[str, Any]]:
    status, payload = auth_request(
        cfg,
        INSPECT_URL,
        method="POST",
        payload={
            "inspectionUrl": inspection_url,
            "siteUrl": cfg["site_url"],
            "languageCode": "en-US",
        },
    )
    if not isinstance(payload, dict):
        payload = {}
    return status, payload


def cmd_inspect(args: argparse.Namespace) -> int:
    cfg = load_local()
    status, payload = inspect_url(cfg, args.url)
    if status != 200:
        print(f"inspect\tfail\thttp={status}")
        return 3
    result = payload.get("inspectionResult") or {}
    print(f"url\t{args.url}")
    print(f"index\t{coverage_line(result)}")
    return 0


def indexed_label(index_status: Dict[str, Any]) -> str:
    coverage = str(index_status.get("coverageState") or "").strip()
    lowered = coverage.lower()
    if "not indexed" in lowered:
        return "Not indexed"
    if "indexed" in lowered:
        return "Index"
    return "Not indexed"


def sitemap_locs(url: str) -> Tuple[str, List[str]]:
    status, payload, raw = _request(url, headers={"Accept": "application/xml,text/xml,*/*"})
    if status != 200 or not raw or raw.startswith("{"):
        raise ConnectError(f"Could not fetch sitemap: {url}")
    import xml.etree.ElementTree as ET

    root = ET.fromstring(raw)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    if root.tag.endswith("sitemapindex"):
        return "index", [el.text.strip() for el in root.findall("sm:sitemap/sm:loc", ns) if el.text]
    return "urlset", [el.text.strip() for el in root.findall("sm:url/sm:loc", ns) if el.text]


def collect_sitemap_urls(start_url: str) -> List[Tuple[str, str]]:
    kind, locs = sitemap_locs(start_url)
    if kind == "urlset":
        return [(start_url, loc) for loc in locs]
    found: List[Tuple[str, str]] = []
    for child in locs:
        child_kind, child_locs = sitemap_locs(child)
        if child_kind == "urlset":
            found.extend((child, loc) for loc in child_locs)
        else:
            for nested in child_locs:
                _, nested_locs = sitemap_locs(nested)
                found.extend((nested, loc) for loc in nested_locs)
    return found


def cmd_inspect_sitemap(args: argparse.Namespace) -> int:
    cfg = load_local()
    rows = collect_sitemap_urls(args.url)
    print(f"sitemap\t{args.url}")
    print(f"urls\t{len(rows)}")
    indexed = 0
    not_indexed = 0
    failed = 0
    for source, page in rows:
        status, payload = inspect_url(cfg, page)
        if status != 200:
            failed += 1
            print(f"Not indexed\t{page}\thttp={status}\t{source}")
            continue
        result = payload.get("inspectionResult") or {}
        index_status = result.get("indexStatusResult") or {}
        if not isinstance(index_status, dict):
            index_status = {}
        label = indexed_label(index_status)
        coverage = str(index_status.get("coverageState") or "unknown")
        if label == "Index":
            indexed += 1
        else:
            not_indexed += 1
        print(f"{label}\t{page}\t{coverage}")
    print(f"summary\tindex={indexed}\tnot_indexed={not_indexed}\tfail={failed}\ttotal={len(rows)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Google Search Console connection.")
    sub = parser.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login", help="One-time Google browser login")
    login.set_defaults(func=cmd_login)
    status = sub.add_parser("status", help="Check auth and property access")
    status.set_defaults(func=cmd_status)
    inspect = sub.add_parser("inspect", help="Inspect one URL")
    inspect.add_argument("url")
    inspect.set_defaults(func=cmd_inspect)
    sitemap = sub.add_parser("inspect-sitemap", help="Inspect every URL in a sitemap or sitemap index")
    sitemap.add_argument("url")
    sitemap.set_defaults(func=cmd_inspect_sitemap)
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
