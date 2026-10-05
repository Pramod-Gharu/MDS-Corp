#!/usr/bin/env python3
"""Build a local HTML dashboard of Google indexing status by sitemap category."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from gsc_connect import (  # noqa: E402
    ConnectError,
    indexed_label,
    inspect_url,
    load_local,
    sitemap_locs,
)

DASHBOARD_DIR = ROOT / "dashboard"
HTML_FILE = DASHBOARD_DIR / "indexing.html"
DATA_FILE = ROOT / ".mds" / "gsc-index.json"
DEFAULT_PORT = 8765
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
SSL_CONTEXT = ssl.create_default_context()

CATEGORIES = [
    {
        "id": "blog",
        "name": "Blog",
        "sitemap": "https://mdsindustrialcorp.com/post-sitemap.xml",
    },
    {
        "id": "pages",
        "name": "Homepage and service pages",
        "sitemap": "https://mdsindustrialcorp.com/page-sitemap.xml",
    },
    {
        "id": "service-areas",
        "name": "Service areas",
        "sitemap": "https://mdsindustrialcorp.com/service-areas-sitemap.xml",
    },
]


def dashboard_url(port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{port}/indexing.html"


def is_server_up(port: int = DEFAULT_PORT) -> bool:
    try:
        urllib.request.urlopen(dashboard_url(port), timeout=1)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def ensure_html() -> None:
    if HTML_FILE.exists():
        return
    data = load_snapshot()
    if not data:
        raise ConnectError("Dashboard is missing. Run: python3 scripts/gsc_dashboard.py refresh")
    write_dashboard(data)


def ensure_server(port: int = DEFAULT_PORT) -> str:
    ensure_html()
    url = dashboard_url(port)
    if is_server_up(port):
        return url
    subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "gsc_dashboard.py"),
            "serve",
            "--port",
            str(port),
            "--no-browser",
        ],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(30):
        time.sleep(0.1)
        if is_server_up(port):
            return url
    raise ConnectError("Dashboard server did not start on 127.0.0.1.")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def title_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.strip("/")
    if not path:
        return "Home"
    slug = path.split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").title()


def parse_urlset(raw: str) -> List[Dict[str, str]]:
    start = raw.find("<?xml")
    if start > 0:
        raw = raw[start:]
    root = ET.fromstring(raw)
    pages = []
    for node in root.findall("sm:url", NS):
        loc = (node.findtext("sm:loc", default="", namespaces=NS) or "").strip()
        if not loc:
            continue
        lastmod = (node.findtext("sm:lastmod", default="", namespaces=NS) or "").strip()
        pages.append({"url": loc, "lastmod": lastmod[:10] if lastmod else ""})
    return pages


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "MDS-Corp-gsc-dashboard"})
    with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_snapshot() -> Dict[str, Any]:
    if not DATA_FILE.exists():
        return {}
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_snapshot(data: Dict[str, Any]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def inspect_categories() -> Dict[str, Any]:
    cfg = load_local()
    status_by_url: Dict[str, Dict[str, str]] = {}
    categories = []
    for item in CATEGORIES:
        kind, locs = sitemap_locs(item["sitemap"])
        if kind != "urlset":
            raise ConnectError(f"Expected a URL sitemap: {item['sitemap']}")
        pages = []
        raw_pages = parse_urlset(fetch_text(item["sitemap"]))
        for page in raw_pages:
            url = page["url"]
            http_status, payload = inspect_url(cfg, url)
            if http_status != 200:
                label = "Not indexed"
                coverage = f"http={http_status}"
                crawled = ""
            else:
                result = payload.get("inspectionResult") or {}
                index_status = result.get("indexStatusResult") or {}
                if not isinstance(index_status, dict):
                    index_status = {}
                label = indexed_label(index_status)
                coverage = str(index_status.get("coverageState") or "unknown")
                crawled = str(index_status.get("lastCrawlTime") or "")[:10]
            row = {
                "url": url,
                "title": title_from_url(url),
                "status": label,
                "coverage": coverage,
                "lastmod": page.get("lastmod") or "",
                "last_crawl": crawled,
            }
            pages.append(row)
            status_by_url[url] = row
        indexed = sum(1 for p in pages if p["status"] == "Index")
        categories.append(
            {
                **item,
                "pages": pages,
                "indexed": indexed,
                "not_indexed": len(pages) - indexed,
                "total": len(pages),
            }
        )
    total = sum(c["total"] for c in categories)
    indexed = sum(c["indexed"] for c in categories)
    return {
        "checked_at": utc_now(),
        "property": cfg["site_url"],
        "source": "Google Search Console URL Inspection",
        "total": total,
        "indexed": indexed,
        "not_indexed": total - indexed,
        "categories": categories,
    }


def render_html(data: Dict[str, Any]) -> str:
    payload = json.dumps(data, indent=2)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Indexing Status | MDS Industrial Racking</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --black: #000000;
      --orange: #FF6C00;
      --text: #222222;
      --muted: #6b6b6b;
      --line: #e6e6e6;
      --bg: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Open Sans", sans-serif;
      font-size: 15px;
      line-height: 1.6;
      color: var(--text);
      background: var(--bg);
    }}
    .nav {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
      padding: 14px 40px;
      background: var(--black);
      color: #fff;
    }}
    .logo {{
      height: 88px;
      width: auto;
      display: block;
    }}
    .tabs {{
      display: flex;
      align-items: center;
      gap: 28px;
      margin: 0 0 28px;
      padding: 0 0 20px;
      list-style: none;
      border-bottom: 1px solid var(--line);
    }}
    .tabs button {{
      background: none;
      border: 0;
      padding: 8px 0;
      color: var(--text);
      font-family: inherit;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
    }}
    .tabs button[aria-selected="true"] {{
      color: var(--orange);
      border-bottom: 2px solid var(--orange);
    }}
    .quote {{
      display: inline-block;
      background: var(--orange);
      color: #fff;
      text-decoration: none;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 12px 18px;
      border-radius: 4px;
    }}
    .hero {{
      position: relative;
      min-height: 220px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #111 center / cover no-repeat url("hero.webp");
    }}
    .hero::before {{
      content: "";
      position: absolute;
      inset: 0;
      background: rgba(0, 0, 0, 0.35);
    }}
    .hero h1 {{
      position: relative;
      margin: 0;
      color: #fff;
      font-size: 36px;
      font-weight: 700;
    }}
    .crumbs {{
      width: min(1080px, calc(100% - 48px));
      margin: -22px auto 0;
      position: relative;
      background: #fff;
      padding: 12px 18px;
      font-size: 13px;
      color: var(--muted);
    }}
    .crumbs span {{ color: var(--orange); }}
    main {{
      width: min(1080px, calc(100% - 48px));
      margin: 0 auto;
      padding: 36px 0 64px;
    }}
    .page-title {{
      margin: 0 0 12px;
      text-align: center;
      color: var(--orange);
      font-size: 28px;
      font-weight: 700;
      line-height: 1.35;
    }}
    .lede {{
      margin: 0 auto 36px;
      max-width: 760px;
      text-align: center;
      color: var(--muted);
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 24px;
      margin: 0 0 28px;
    }}
    .stat b {{
      display: block;
      font-size: 32px;
      font-weight: 700;
      color: var(--text);
      line-height: 1.1;
    }}
    .stat span {{
      color: var(--muted);
      font-size: 14px;
    }}
    .section {{
      margin: 0 0 28px;
    }}
    .section h2 {{
      margin: 0 0 8px;
      font-size: 22px;
      font-weight: 700;
      color: var(--text);
    }}
    .section p {{
      margin: 0 0 16px;
      color: var(--muted);
    }}
    .toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    input[type="search"] {{
      width: 280px;
      padding: 9px 12px;
      border: 1px solid var(--line);
      font-family: inherit;
      font-size: 14px;
    }}
    input[type="search"]:focus {{
      outline: none;
      border-color: var(--orange);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      padding: 14px 0;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      font-size: 13px;
      font-weight: 700;
      color: var(--text);
    }}
    td {{ color: var(--muted); }}
    td a {{
      color: var(--text);
      text-decoration: none;
      font-weight: 600;
    }}
    td a:hover {{ color: var(--orange); }}
    .status {{
      font-weight: 700;
      color: var(--text);
    }}
    .status.miss {{ color: var(--orange); }}
    .path {{ font-size: 13px; font-weight: 400; color: var(--muted); }}
    footer {{
      margin-top: 28px;
      color: var(--muted);
      font-size: 13px;
    }}
    @media (max-width: 800px) {{
      .nav {{ padding: 10px 16px; flex-wrap: wrap; }}
      .tabs {{ gap: 16px; }}
      .stats {{ grid-template-columns: 1fr 1fr; }}
      .hero h1 {{ font-size: 28px; }}
      main, .crumbs {{ width: calc(100% - 32px); }}
    }}
  </style>
</head>
<body>
  <header class="nav">
    <a href="https://mdsindustrialcorp.com/"><img class="logo" src="logo.jpg" alt="MDS Industrial Racking" /></a>
    <a class="quote" href="https://mdsindustrialcorp.com/contact-us/">Get a free quote</a>
  </header>
  <section class="hero">
    <h1>Indexing Status</h1>
  </section>
  <div class="crumbs">Home / <span>Indexing Status</span></div>
  <main>
    <h2 class="page-title">MDS Industrial Racking – Google Search indexing for every sitemap URL</h2>
    <p class="lede">Checked <span id="checked"></span>. Status comes from Google Search Console URL Inspection, grouped the same way as the live sitemaps: Blog, homepage and service pages, and service areas.</p>
    <div class="stats" id="stats"></div>
    <ul class="tabs" id="tabs"></ul>
    <div class="section">
      <h2 id="section-title">Blog</h2>
      <p id="section-copy"></p>
      <div class="toolbar">
        <input type="search" id="q" placeholder="Filter by page name or URL" />
      </div>
      <table>
        <thead>
          <tr>
            <th>Page</th>
            <th>Status</th>
            <th>Google coverage</th>
            <th>Last updated</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
    <footer id="foot"></footer>
  </main>
  <script>
    const DATA = {payload};
    let active = "blog";
    function esc(s) {{
      return String(s || "").replace(/[&<>"']/g, (c) => ({{
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }})[c]);
    }}
    function fmtDate(iso) {{
      if (!iso) return "";
      return iso.replace("T", " ").replace("+00:00", " UTC").replace("Z", " UTC");
    }}
    function render() {{
      const q = document.getElementById("q").value.toLowerCase();
      const cat = DATA.categories.find((c) => c.id === active) || DATA.categories[0];
      const names = {{ blog: "Blog", pages: "Pages", "service-areas": "Service Areas" }};
      document.getElementById("checked").textContent = fmtDate(DATA.checked_at);
      document.getElementById("stats").innerHTML = [
        ["Sitemap URLs", DATA.total],
        ["Index", DATA.indexed],
        ["Not indexed", DATA.not_indexed],
        [names[cat.id] || cat.name, cat.indexed + " / " + cat.total]
      ].map(([k, v]) => `<div class="stat"><b>${{v}}</b><span>${{k}}</span></div>`).join("");
      document.getElementById("section-title").textContent = cat.name;
      const missed = cat.pages.filter((p) => p.status !== "Index").length;
      document.getElementById("section-copy").textContent = missed
        ? cat.indexed + " of " + cat.total + " URLs in this sitemap are indexed. " + missed + " currently not indexed."
        : "All " + cat.total + " URLs in this sitemap are indexed.";
      document.getElementById("tabs").innerHTML = DATA.categories.map((c) =>
        `<li><button type="button" aria-selected="${{c.id === active}}" data-id="${{c.id}}">${{esc(names[c.id] || c.name)}}</button></li>`
      ).join("");
      document.querySelectorAll(".tabs button").forEach((btn) => {{
        btn.onclick = () => {{ active = btn.dataset.id; render(); }};
      }});
      const rows = cat.pages.filter((p) =>
        !q || (p.title + " " + p.url).toLowerCase().includes(q)
      );
      document.getElementById("rows").innerHTML = rows.map((p) => {{
        const ok = p.status === "Index";
        const path = p.url.replace("https://mdsindustrialcorp.com", "") || "/";
        return `<tr>
          <td><a href="${{esc(p.url)}}" target="_blank" rel="noreferrer">${{esc(p.title)}}</a><div class="path">${{esc(path)}}</div></td>
          <td><span class="status ${{ok ? "" : "miss"}}">${{esc(p.status)}}</span></td>
          <td>${{esc(p.coverage)}}</td>
          <td>${{esc(p.lastmod)}}</td>
        </tr>`;
      }}).join("");
      document.getElementById("foot").textContent =
        "Source: " + DATA.source + " · " + DATA.property +
        " · post-sitemap.xml, page-sitemap.xml, and service-areas-sitemap.xml.";
    }}
    document.getElementById("q").addEventListener("input", render);
    render();
  </script>
</body>
</html>
"""


def write_dashboard(data: Dict[str, Any]) -> Path:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    HTML_FILE.write_text(render_html(data), encoding="utf-8")
    save_snapshot(data)
    return HTML_FILE


def cmd_refresh(_: argparse.Namespace) -> int:
    data = inspect_categories()
    path = write_dashboard(data)
    print(f"wrote\t{path}")
    print(f"summary\tindex={data['indexed']}\tnot_indexed={data['not_indexed']}\ttotal={data['total']}")
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    data = load_snapshot()
    if not data:
        raise ConnectError("No saved snapshot. Run: python3 scripts/gsc_dashboard.py refresh")
    path = write_dashboard(data)
    print(f"wrote\t{path}")
    if args.open:
        url = ensure_server()
        webbrowser.open(url)
        print(f"opened\t{url}")
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    url = ensure_server(args.port)
    webbrowser.open(url)
    print(f"opened\t{url}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    ensure_html()

    class DashboardHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(DASHBOARD_DIR), **k)

        def translate_path(self, path: str) -> str:
            if path.split("?", 1)[0] in {"/", "/index.html"}:
                path = "/indexing.html"
            return super().translate_path(path)

        def log_message(self, format: str, *log_args: Any) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = dashboard_url(args.port)
    print(f"serving\t{url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local GSC indexing dashboard.")
    sub = parser.add_subparsers(dest="command", required=True)
    refresh = sub.add_parser("refresh", help="Inspect sitemaps in GSC and rebuild the HTML dashboard")
    refresh.set_defaults(func=cmd_refresh)
    write = sub.add_parser("write", help="Rebuild HTML from the last saved snapshot")
    write.add_argument("--open", action="store_true")
    write.set_defaults(func=cmd_write)
    open_p = sub.add_parser("open", help="Open the dashboard at http://127.0.0.1:8765/")
    open_p.add_argument("--port", type=int, default=DEFAULT_PORT)
    open_p.set_defaults(func=cmd_open)
    serve = sub.add_parser("serve", help="Serve the dashboard at localhost")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--no-browser", action="store_true")
    serve.set_defaults(func=cmd_serve)
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
