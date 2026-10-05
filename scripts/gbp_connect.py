#!/usr/bin/env python3
"""Talk to Google Business Profile. Credentials stay in a local gitignored file."""

from __future__ import annotations

import argparse
import base64
import csv
import html
import io
import json
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LOCAL_FILE = ROOT / ".mds" / "gbp-oauth.json"
SHEET_FILE = ROOT / ".mds" / "gbp-sheet.json"
SCOPE = "https://www.googleapis.com/auth/business.manage"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
INFO_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"
POSTS_BASE = "https://mybusiness.googleapis.com/v4"
USER_AGENT = "MDS-Corp-gbp-connector"
SSL_CONTEXT = ssl.create_default_context()
LOGIN_PORT = 8081
UTM_SOURCE = "GBP_post"
UTM_MEDIUM = "page_share"


class ConnectError(RuntimeError):
    pass


def load_local() -> Dict[str, Any]:
    if not LOCAL_FILE.exists():
        raise ConnectError("Local GBP connection file is missing. Run: python3 scripts/gbp_save_oauth.py")
    try:
        data = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConnectError("Local GBP connection file is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ConnectError("Local GBP connection file must be a JSON object.")
    client_id = str(data.get("client_id") or "").strip()
    client_secret = str(data.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ConnectError("Local GBP file is missing client_id or client_secret.")
    data["client_id"] = client_id
    data["client_secret"] = client_secret
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
) -> Tuple[int, Any]:
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
        payload = {"ok": False}
    return status, payload


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
    status, payload = _request(
        TOKEN_URL,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body,
    )
    if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
        hint = "Google login failed."
        if isinstance(payload, dict) and payload.get("error") == "invalid_client":
            hint += " Recheck the Client ID and Client secret."
        raise ConnectError(hint)
    return payload


def refresh_access_token(cfg: Dict[str, Any]) -> str:
    refresh_token = str(cfg.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ConnectError("Not logged in yet. Run: python3 scripts/gbp_connect.py login")
    body = urllib.parse.urlencode(
        {
            "refresh_token": refresh_token,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    status, payload = _request(
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


def auth_request(
    cfg: Dict[str, Any],
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Any]:
    token = refresh_access_token(cfg)
    body = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-GOOG-API-FORMAT-VERSION": "2",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return _request(url, method=method, headers=headers, body=body)


def open_in_chrome(url: str) -> None:
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


def list_accounts(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    status, payload = auth_request(cfg, ACCOUNTS_URL)
    if status == 403:
        raise ConnectError(
            "Google denied account access. Enable My Business Account Management API "
            "on the approved Cloud project, then try again."
        )
    if status == 429:
        raise ConnectError("Quota is still zero or exhausted. Confirm Basic Access is approved.")
    if status != 200 or not isinstance(payload, dict):
        raise ConnectError(f"Could not list Business Profile accounts (http={status}).")
    accounts = payload.get("accounts") or []
    return [item for item in accounts if isinstance(item, dict)]


def _google_error(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    err = payload.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or "").strip()
    return str(payload.get("message") or "").strip()


def normalize_account_name(account_name: str) -> str:
    name = account_name.strip().lstrip("/")
    if name.startswith("accounts/"):
        return name
    return f"accounts/{name}"


def list_locations(cfg: Dict[str, Any], account_name: str) -> List[Dict[str, Any]]:
    parent = normalize_account_name(account_name)
    candidates = [
        (
            f"{INFO_BASE}/{parent}/locations"
            "?readMask=name,title,storefrontAddress,websiteUri&pageSize=100"
        ),
        f"{POSTS_BASE}/{parent}/locations?pageSize=100",
    ]
    last_status = 0
    last_hint = ""
    for url in candidates:
        status, payload = auth_request(cfg, url)
        last_status = status
        last_hint = _google_error(payload)
        if status == 200 and isinstance(payload, dict):
            locations = payload.get("locations") or []
            return [item for item in locations if isinstance(item, dict)]
    extra = f" {last_hint}" if last_hint else ""
    if last_status == 404:
        raise ConnectError(
            "Could not list locations (http=404)."
            " Enable Google My Business API and My Business Business Information API"
            " on the approved Cloud project, then run status again."
            f"{extra}"
        )
    raise ConnectError(f"Could not list locations (http={last_status}).{extra}")


def location_label(loc: Dict[str, Any]) -> str:
    return str(loc.get("title") or loc.get("locationName") or loc.get("name") or "").strip()


def location_website(loc: Dict[str, Any]) -> str:
    return str(loc.get("websiteUri") or loc.get("websiteUrl") or "").strip().lower()


def pick_location(cfg: Dict[str, Any]) -> Tuple[str, str]:
    saved = str(cfg.get("location_name") or "").strip()
    saved_title = str(cfg.get("location_title") or "").strip()
    if saved:
        return saved, saved_title or saved
    accounts = list_accounts(cfg)
    if not accounts:
        raise ConnectError("No Business Profile accounts were returned for this Google login.")
    found: List[Dict[str, Any]] = []
    for account in accounts:
        name = str(account.get("name") or "")
        if not name:
            continue
        for loc in list_locations(cfg, name):
            loc["_account_name"] = normalize_account_name(name)
            found.append(loc)
    usable = [loc for loc in found if str(loc.get("name") or "")]
    if not usable:
        raise ConnectError("No locations were returned for this Google login.")

    chosen = None
    for loc in usable:
        if "mdsindustrialcorp.com" in location_website(loc):
            chosen = loc
            break
    if chosen is None:
        for loc in usable:
            if location_label(loc).lower() == "mds industrial equipment":
                chosen = loc
                break
    if chosen is None and len(usable) == 1:
        chosen = usable[0]
    if chosen is None:
        print("locations:")
        for loc in usable:
            print(f"- {location_label(loc)}")
        raise ConnectError("More than one location found. Say which listing to use.")

    loc_name = str(chosen.get("name") or "")
    title = location_label(chosen)
    cfg["location_name"] = loc_name
    cfg["location_title"] = title
    account_name = str(chosen.get("_account_name") or "").strip()
    if account_name:
        cfg["account_name"] = normalize_account_name(account_name)
    save_local(cfg)
    return loc_name, title


def cmd_login(_: argparse.Namespace) -> int:
    cfg = load_local()
    host = "127.0.0.1"
    redirect_uri = f"http://{host}:{LOGIN_PORT}/"
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
    print("Choose the Google account that manages the MDS Industrial Business Profile, then click Allow.")

    def open_browser() -> None:
        open_in_chrome(url)

    code, used_redirect = wait_for_code(host, LOGIN_PORT, open_browser)
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
        print("Run: python3 scripts/gbp_connect.py login")
        return 2
    accounts = list_accounts(cfg)
    print("auth\tok")
    print(f"accounts\t{len(accounts)}")
    loc_name, title = pick_location(cfg)
    print(f"location\tok\t{title}")
    print(f"location_id\t{loc_name}")
    return 0


def with_utm(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if not parsed.scheme:
        parsed = urllib.parse.urlparse(f"https://{url.strip()}")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query["utm_source"] = [UTM_SOURCE]
    query["utm_medium"] = [UTM_MEDIUM]
    new_query = urllib.parse.urlencode(query, doseq=True)
    path = parsed.path or "/"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", new_query, ""))


def blog_slug(url: str) -> str:
    path = urllib.parse.urlparse(url).path.strip("/")
    if not path:
        raise ConnectError("The blog URL has no article path.")
    return path.split("/")[-1]


def fetch_blog(url: str) -> Dict[str, str]:
    parsed = urllib.parse.urlparse(url.strip())
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    slug = blog_slug(url)
    api = f"{origin}/wp-json/wp/v2/posts?slug={urllib.parse.quote(slug)}&_embed=1"
    status, payload = _request(api)
    if status != 200 or not isinstance(payload, list) or not payload:
        raise ConnectError("Could not load that WordPress article.")
    post = payload[0] if isinstance(payload[0], dict) else {}
    raw_title = ((post.get("title") or {}) if isinstance(post.get("title"), dict) else {}).get("rendered")
    title = html.unescape(str(raw_title or "")).strip()
    link = str(post.get("link") or url).strip()
    image = ""
    embedded = (post.get("_embedded") or {}).get("wp:featuredmedia") or []
    if embedded and isinstance(embedded[0], dict):
        image = str(embedded[0].get("source_url") or "").strip()
        if not image:
            sizes = ((embedded[0].get("media_details") or {}).get("sizes") or {})
            for key in ("full", "large", "medium_large", "medium"):
                item = sizes.get(key) or {}
                if isinstance(item, dict) and item.get("source_url"):
                    image = str(item["source_url"]).strip()
                    break
    if not title:
        raise ConnectError("The WordPress article has no title.")
    if not image:
        raise ConnectError("The WordPress article has no featured image.")
    return {"title": title, "link": link, "image": image}


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
        return resp.read()


def convert_bytes_to_jpeg(raw: bytes) -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="mds-gbp-"))
    src = tmp_dir / "source.bin"
    out = tmp_dir / "post.jpg"
    src.write_bytes(raw)
    result = subprocess.run(
        ["sips", "-s", "format", "jpeg", str(src), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not out.exists():
        raise ConnectError("Could not convert the image to JPEG for Google.")
    return out


def convert_to_jpeg(image_url: str) -> Path:
    return convert_bytes_to_jpeg(download_bytes(image_url))


def upload_jpeg_to_wordpress(jpeg_path: Path) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    import wp_connect

    wp = wp_connect.load_local()
    if not wp.get("user") or not wp.get("secret"):
        raise ConnectError("WordPress credentials are required to host a JPEG Google can use.")
    token = base64.b64encode(f"{wp['user']}:{wp['secret']}".encode("utf-8")).decode("ascii")
    data = jpeg_path.read_bytes()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Authorization": f"Basic {token}",
        "Content-Type": "image/jpeg",
        "Content-Disposition": 'attachment; filename="gbp-blog-post.jpg"',
    }
    req = urllib.request.Request(
        f"{wp['site']}/wp-json/wp/v2/media",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise ConnectError(f"Could not upload a JPEG to WordPress (http={exc.code}).") from exc
    source = str(payload.get("source_url") or "").strip()
    if not source:
        raise ConnectError("WordPress did not return an image URL.")
    return source


def drive_file_id(link: str) -> str:
    text = link.strip()
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", text)
    if match:
        return match.group(1)
    parsed = urllib.parse.urlparse(text)
    query = urllib.parse.parse_qs(parsed.query)
    if query.get("id"):
        return query["id"][0]
    raise ConnectError("The Image cell is not a Google Drive file link.")


def download_drive_bytes(link: str) -> bytes:
    file_id = drive_file_id(link)
    url = f"https://drive.google.com/uc?export=download&id={urllib.parse.quote(file_id)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
            data = resp.read()
            content_type = str(resp.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as exc:
        raise ConnectError("Could not download the Drive image. Confirm Anyone with the link → Viewer.") from exc
    if "text/html" in content_type.lower() or data[:15].lstrip().lower().startswith(b"<!doctype") or data[:6].lstrip().lower().startswith(b"<html"):
        html_text = data.decode("utf-8", errors="replace")
        confirm = re.search(r"confirm=([0-9A-Za-z_-]+)", html_text)
        if not confirm:
            raise ConnectError("Google Drive did not return the image. Share the file as Anyone with the link.")
        confirm_url = (
            f"https://drive.google.com/uc?export=download&id={urllib.parse.quote(file_id)}"
            f"&confirm={confirm.group(1)}"
        )
        data = download_bytes(confirm_url)
    if len(data) < 1024:
        raise ConnectError("The Drive file is too small to use as a Google post image.")
    return data


def gbp_photo_url(image_url: str) -> str:
    lowered = image_url.lower()
    if "drive.google.com" in lowered:
        jpeg = convert_bytes_to_jpeg(download_drive_bytes(image_url))
        return upload_jpeg_to_wordpress(jpeg)
    path = image_url.lower().split("?")[0]
    if path.endswith((".jpg", ".jpeg", ".png")):
        return image_url
    jpeg = convert_to_jpeg(image_url)
    return upload_jpeg_to_wordpress(jpeg)


def sheet_url() -> str:
    if not SHEET_FILE.exists():
        raise ConnectError("Local Google Sheet file is missing (.mds/gbp-sheet.json).")
    data = json.loads(SHEET_FILE.read_text(encoding="utf-8"))
    url = str((data or {}).get("sheet_url") or "").strip()
    if not url:
        raise ConnectError("Local Google Sheet file is missing sheet_url.")
    return url


def sheet_csv_url(edit_url: str) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", edit_url)
    if not match:
        raise ConnectError("That is not a Google Sheet link.")
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"


def fetch_keyword_rows() -> List[Dict[str, str]]:
    raw = download_bytes(sheet_csv_url(sheet_url())).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    rows = []
    for item in reader:
        clean = {(k or "").strip(): str(v or "").strip() for k, v in item.items()}
        keyword = clean.get("Keywords") or clean.get("Keyword") or ""
        description = clean.get("Description") or keyword
        page = clean.get("URL") or ""
        image = clean.get("Image") or ""
        if not keyword:
            continue
        rows.append(
            {
                "keyword": keyword,
                "description": description,
                "url": page,
                "image": image,
            }
        )
    return rows


def find_keyword_row(query: str) -> Dict[str, str]:
    wanted = " ".join(query.split()).strip().lower()
    rows = fetch_keyword_rows()
    if not rows:
        raise ConnectError("The Google Sheet has no keyword rows.")
    for row in rows:
        if row["keyword"].lower() == wanted:
            return row
    for row in rows:
        if wanted in row["keyword"].lower() or row["keyword"].lower() in wanted:
            return row
    names = ", ".join(row["keyword"] for row in rows)
    raise ConnectError(f"No sheet row matched that keyword. Available: {names}")


def create_local_post(cfg: Dict[str, Any], summary: str, page_url: str, image_url: str) -> Tuple[str, Dict[str, Any], str]:
    loc_name, title = pick_location(cfg)
    parent = post_parent(cfg, loc_name)
    endpoint = f"{POSTS_BASE}/{parent}/localPosts"
    photo = gbp_photo_url(image_url)
    payload = {
        "languageCode": "en",
        "summary": summary,
        "topicType": "STANDARD",
        "callToAction": {
            "actionType": "LEARN_MORE",
            "url": with_utm(page_url),
        },
        "media": [
            {
                "mediaFormat": "PHOTO",
                "sourceUrl": photo,
            }
        ],
    }
    status, data = auth_request(cfg, endpoint, method="POST", payload=payload)
    hint = _google_error(data)
    extra = f" {hint}" if hint else ""
    if status not in {200, 201} or not isinstance(data, dict) or not data.get("name"):
        raise ConnectError(f"Could not create the Google post (http={status}).{extra}")
    return title, data, photo


def post_parent(cfg: Dict[str, Any], loc_name: str) -> str:
    loc_name = loc_name.strip().lstrip("/")
    if loc_name.startswith("accounts/") and "/locations/" in loc_name:
        return loc_name
    account = str(cfg.get("account_name") or "").strip()
    if not account:
        accounts = list_accounts(cfg)
        if len(accounts) != 1:
            raise ConnectError("Could not determine the Business Profile account path for posting.")
        account = normalize_account_name(str(accounts[0].get("name") or ""))
        cfg["account_name"] = account
        save_local(cfg)
    loc_part = loc_name if loc_name.startswith("locations/") else f"locations/{loc_name}"
    return f"{normalize_account_name(account)}/{loc_part}"


def cmd_post(args: argparse.Namespace) -> int:
    cfg = load_local()
    summary = " ".join(args.text).strip()
    if not summary:
        raise ConnectError("Post text is empty.")
    if not args.url:
        raise ConnectError("A Learn more URL is required. Use --url.")
    image_url = str(args.image or "").strip()
    if not image_url:
        raise ConnectError("An image URL is required. Use --image, or use from-blog.")
    title, data, photo = create_local_post(cfg, summary, args.url, image_url)
    print("post\tok")
    print(f"location\t{title}")
    print(f"state\t{data.get('state') or ''}")
    print("button\tLEARN_MORE")
    print(f"link\t{with_utm(args.url)}")
    print(f"image\t{photo}")
    return 0


def cmd_from_blog(args: argparse.Namespace) -> int:
    cfg = load_local()
    blog = fetch_blog(args.url)
    title, data, photo = create_local_post(cfg, blog["title"], blog["link"], blog["image"])
    print("post\tok")
    print(f"location\t{title}")
    print(f"state\t{data.get('state') or ''}")
    print(f"description\t{blog['title']}")
    print(f"image\t{photo}")
    print("button\tLEARN_MORE")
    print(f"link\t{with_utm(blog['link'])}")
    return 0


def cmd_keywords(_: argparse.Namespace) -> int:
    rows = fetch_keyword_rows()
    print(f"rows\t{len(rows)}")
    for row in rows:
        print(f"{row['keyword']}\t{row['description']}")
    return 0


def cmd_from_keyword(args: argparse.Namespace) -> int:
    cfg = load_local()
    row = find_keyword_row(" ".join(args.keyword).strip())
    if not row["url"]:
        raise ConnectError(f"The sheet row for '{row['keyword']}' has no URL.")
    if not row["image"]:
        raise ConnectError(f"The sheet row for '{row['keyword']}' has no Image Drive link.")
    title, data, photo = create_local_post(cfg, row["description"], row["url"], row["image"])
    print("post\tok")
    print(f"location\t{title}")
    print(f"keyword\t{row['keyword']}")
    print(f"state\t{data.get('state') or ''}")
    print(f"description\t{row['description']}")
    print("button\tLEARN_MORE")
    print(f"link\t{with_utm(row['url'])}")
    print(f"image\t{photo}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Google Business Profile connection.")
    sub = parser.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login", help="One-time Google browser login")
    login.set_defaults(func=cmd_login)
    status = sub.add_parser("status", help="Check auth and the MDS location")
    status.set_defaults(func=cmd_status)
    post = sub.add_parser("post", help="Publish one standard Google Business post")
    post.add_argument("text", nargs="+", help="Post description text")
    post.add_argument("--url", required=True, help="Learn more link")
    post.add_argument("--image", help="Public image URL")
    post.set_defaults(func=cmd_post)
    from_blog = sub.add_parser("from-blog", help="Create a GBP post from a WordPress article")
    from_blog.add_argument("url", help="WordPress article URL")
    from_blog.set_defaults(func=cmd_from_blog)
    keywords = sub.add_parser("keywords", help="List keyword rows from the Google Sheet")
    keywords.set_defaults(func=cmd_keywords)
    from_keyword = sub.add_parser("from-keyword", help="Create a GBP post from a Google Sheet keyword row")
    from_keyword.add_argument("keyword", nargs="+", help="Keyword text from the sheet")
    from_keyword.set_defaults(func=cmd_from_keyword)
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
