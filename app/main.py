import os
import httpx
import re
import hashlib
import bleach
import markdown

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# load .env
load_dotenv()

# config
APP_NAME = os.getenv("APP_NAME", "md-embed-api")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
RAW_BASE = os.getenv("GITHUB_RAW_BASE", "https://raw.githubusercontent.com")
CACHE_MAX_AGE = int(os.getenv("CACHE_MAX_AGE", "300"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]

app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

repo_re = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ref_re = re.compile(r"^[A-Za-z0-9_.\-\/]+$")
path_re = re.compile(r"^[^\0]+$")

ALLOWED_TAGS = bleach.sanitizer.ALLOWED_TAGS.union(
    {
        "p",
        "pre",
        "code",
        "span",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "blockquote",
        "hr",
        "br",
        "ul",
        "ol",
        "li",
        "em",
        "strong",
        "a",
        "img",
        "details",
        "summary",
    }
)
ALLOWED_ATTRS = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title", "width", "height"],
    "code": ["class"],
    "span": ["class"],
    "div": ["class"],
    "pre": ["class"],
}


def src_url(repo: str, path: str, ref: str) -> str:
    return f"{RAW_BASE}/{repo}/{ref}/{path}"


def etag_for(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def cache_headers(resp: Response, etag: str) -> None:
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = f"public, max-age={CACHE_MAX_AGE}"


def render_md(md_text: str) -> str:
    html = markdown.markdown(
        md_text,
        extensions=[
            "fenced_code",
            "codehilite",
            "tables",
            "toc",
            "sane_lists",
            "admonition",
            "nl2br",
        ],
    )
    safe = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=False)
    return safe


GITHUB_MARKDOWN_LIGHT = "https://cdn.jsdelivr.net/npm/github-markdown-css@5.7.0/github-markdown-light.min.css"
GITHUB_MARKDOWN_DARK = "https://cdn.jsdelivr.net/npm/github-markdown-css@5.7.0/github-markdown-dark.min.css"
PYGMENTS_LIGHT = "https://cdn.jsdelivr.net/npm/pygments-css@0.1.0/default.css"
PYGMENTS_DARK = "https://cdn.jsdelivr.net/npm/pygments-css@0.1.0/native.css"

HTML_TEMPLATE = """<!-- Rendered via md-embed-api — https://github.com/Awerito/md-embed-api -->
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link id="ghcss" rel="stylesheet" href="{gh_light}">
<link id="pygcss" rel="stylesheet" href="{pyg_light}">
<style>
:root {{
  color-scheme: light dark;
  --gh-bg-light:#ffffff;
  --gh-bg-dark:#0d1117;
  --gh-fg-light:#24292f;
  --gh-fg-dark:#c9d1d9;
  --gh-border-light:#d0d7de;
  --gh-border-dark:#30363d;
  --gh-header-light:#f6f8fa;
  --gh-header-dark:#161b22;
  --gh-shadow-light:0 1px 3px rgba(27,31,36,0.12);
  --gh-shadow-dark:0 1px 3px rgba(0,0,0,0.4);
  --gh-link-light:#0969da;
  --gh-link-dark:#2f81f7;
}}

body {{
  margin:0;
  background:transparent;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif,"Apple Color Emoji","Segoe UI Emoji";
}}

.container {{
  box-sizing:border-box;
  max-width:{max_width}px;
  margin:0 auto;
  padding:{padding};
}}

.gist-frame {{
  border-radius:6px;
  border:1px solid var(--gh-border-light);
  background:var(--gh-bg-light);
  box-shadow:var(--gh-shadow-light);
  overflow:hidden;
}}

@media (prefers-color-scheme: dark) {{
  .gist-frame {{
    border-color:var(--gh-border-dark);
    background:var(--gh-bg-dark);
    box-shadow:var(--gh-shadow-dark);
  }}
}}

.header {{
  display:flex;
  justify-content:space-between;
  align-items:center;
  background:var(--gh-header-light);
  border-bottom:1px solid var(--gh-border-light);
  padding:8px 12px;
  font-size:13px;
  font-weight:600;
  color:var(--gh-fg-light);
}}

@media (prefers-color-scheme: dark) {{
  .header {{
    background:var(--gh-header-dark);
    border-color:var(--gh-border-dark);
    color:var(--gh-fg-dark);
  }}
}}

.header .meta {{
  font-weight:500;
  opacity:0.7;
  font-size:12px;
}}

.markdown-body {{
  padding:16px;
  font-size:15px;
  line-height:1.6;
}}

.markdown-body a {{
  color:var(--gh-link-light);
}}

@media (prefers-color-scheme: dark) {{
  .markdown-body a {{
    color:var(--gh-link-dark);
  }}
}}

.footer {{
  border-top:1px solid var(--gh-border-light);
  background:var(--gh-header-light);
  padding:6px 12px;
  display:flex;
  justify-content:flex-end;
}}

.footer a {{
  color:var(--gh-link-light);
  font-size:12px;
  text-decoration:none;
}}

@media (prefers-color-scheme: dark) {{
  .footer {{
    border-color:var(--gh-border-dark);
    background:var(--gh-header-dark);
  }}
  .footer a {{
    color:var(--gh-link-dark);
  }}
}}
</style>

<body>
<div class="container">
  <div class="gist-frame">
    <div class="header">
      <div class="title">{title}</div>
      <div class="meta">{repo}@{ref}</div>
    </div>
    <article class="markdown-body">
      {content}
    </article>
    <div class="footer">
      <a href="{raw_url}" target="_blank" rel="noopener">view raw</a>
    </div>
  </div>
</div>
</body>
</html>
<!-- End of md-embed-api render — https://github.com/Awerito/md-embed-api -->
"""


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "name": APP_NAME, "version": APP_VERSION}


@app.get("/md/raw")
async def md_raw(
    repo: str = Query(..., description="owner/repo"),
    path: str = Query(..., description="path/to/file.md"),
    ref: str = Query("main", description="branch|tag|sha"),
) -> Response:
    if not repo_re.match(repo) or not ref_re.match(ref) or not path_re.match(path):
        raise HTTPException(400, "invalid parameters")
    url = src_url(repo, path, ref)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"User-Agent": f"{APP_NAME}/1.0"})
    if r.status_code != 200:
        raise HTTPException(r.status_code, "upstream error")
    body = r.content
    et = etag_for(body)
    resp = PlainTextResponse(content=body, media_type="text/markdown; charset=utf-8")
    cache_headers(resp, et)
    return resp


@app.get("/md/html")
async def md_html(
    repo: str = Query(..., description="owner/repo"),
    path: str = Query(..., description="path/to/file.md"),
    ref: str = Query("main", description="branch|tag|sha"),
    max_width: int = Query(860, ge=320, le=1920),
    padding: str = Query("16px"),
    title: str | None = Query(None),
) -> Response:
    if not repo_re.match(repo) or not ref_re.match(ref) or not path_re.match(path):
        raise HTTPException(400, "invalid parameters")
    url = src_url(repo, path, ref)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"User-Agent": f"{APP_NAME}/1.0"})
    if r.status_code != 200:
        raise HTTPException(r.status_code, "upstream error")
    md_text = r.text
    html_body = render_md(md_text)
    raw_url = url
    file_title = title or os.path.basename(path)
    full = HTML_TEMPLATE.format(
        gh_light=GITHUB_MARKDOWN_LIGHT,
        gh_dark=GITHUB_MARKDOWN_DARK,
        pyg_light=PYGMENTS_LIGHT,
        pyg_dark=PYGMENTS_DARK,
        content=html_body,
        max_width=max_width,
        padding=padding,
        title=file_title,
        repo=repo,
        ref=ref,
        raw_url=raw_url,
    )
    et = etag_for(md_text.encode("utf-8"))
    resp = HTMLResponse(content=full)
    cache_headers(resp, et)
    return resp
