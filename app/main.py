import re
import httpx
import bleach
import hashlib
import markdown

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, HTMLResponse, PlainTextResponse


app = FastAPI(title="md-embed-api", version="v1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

RAW_BASE = "https://raw.githubusercontent.com"

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


def cache_headers(resp: Response, etag: str, max_age: int = 300) -> None:
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = f"public, max-age={max_age}"


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

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link id="ghcss" rel="stylesheet" href="{gh_light}">
<link id="pygcss" rel="stylesheet" href="{pyg_light}">
<style>
:root {{ color-scheme: light dark; }}
@media (prefers-color-scheme: dark) {{
  #ghcss {{ content: url({gh_dark}); }}
  #pygcss {{ content: url({pyg_dark}); }}
}}
body {{ margin:0; padding:0; background:transparent; }}
.article {{ padding: 0; }}
.container {{ box-sizing:border-box; max-width:{max_width}px; margin:0 auto; padding:{padding}; }}
.markdown-body pre {{ overflow:auto; }}
</style>
<body>
<div class="container">
  <article class="markdown-body article">
  {content}
  </article>
</div>
</body>
</html>
"""


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "name": app.title, "version": app.version}


@app.get("/md/raw")
async def md_raw(
    repo: str = Query(..., description="owner/repo"),
    path: str = Query(..., description="path/to/file.md"),
    ref: str = Query("master", description="branch|tag|sha"),
) -> Response:
    if not repo_re.match(repo) or not ref_re.match(ref) or not path_re.match(path):
        raise HTTPException(400, "invalid parameters")
    url = src_url(repo, path, ref)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"User-Agent": "md-embed-api/1.0"})
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
    ref: str = Query("master", description="branch|tag|sha"),
    max_width: int = Query(860, ge=320, le=1920),
    padding: str = Query("16px"),
) -> Response:
    if not repo_re.match(repo) or not ref_re.match(ref) or not path_re.match(path):
        raise HTTPException(400, "invalid parameters")
    url = src_url(repo, path, ref)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"User-Agent": "md-embed-api/1.0"})
    if r.status_code != 200:
        raise HTTPException(r.status_code, "upstream error")
    md_text = r.text
    html_body = render_md(md_text)
    full = HTML_TEMPLATE.format(
        gh_light=GITHUB_MARKDOWN_LIGHT,
        gh_dark=GITHUB_MARKDOWN_DARK,
        pyg_light=PYGMENTS_LIGHT,
        pyg_dark=PYGMENTS_DARK,
        content=html_body,
        max_width=max_width,
        padding=padding,
    )
    et = etag_for(md_text.encode("utf-8"))
    resp = HTMLResponse(content=full)
    cache_headers(resp, et)
    return resp
