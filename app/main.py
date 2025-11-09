import os
import re
import httpx
import hashlib
import bleach
import markdown

from urllib.parse import urlparse, quote
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Response, Request
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
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://md-embed.grye.org")

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


def blob_url(repo: str, path: str, ref: str) -> str:
    return f"https://github.com/{repo}/blob/{ref}/{path}"


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
        ],
    )
    safe = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=False)
    return safe


GITHUB_MARKDOWN_LIGHT = "https://cdn.jsdelivr.net/npm/github-markdown-css@5.7.0/github-markdown-light.min.css"
GITHUB_MARKDOWN_DARK = "https://cdn.jsdelivr.net/npm/github-markdown-css@5.7.0/github-markdown-dark.min.css"
PYGMENTS_LIGHT = "https://cdn.jsdelivr.net/npm/pygments-css@0.1.0/default.css"
PYGMENTS_DARK = "https://cdn.jsdelivr.net/npm/pygments-css@0.1.0/native.css"
GIST_EMBED_CSS = "https://github.githubassets.com/assets/gist-embed-0ac919313390.css"

FRAGMENT_TEMPLATE = """
<link rel="stylesheet" href="{gist_css}">
<link id="ghcss" rel="stylesheet" href="{gh_light}">
<link id="pygcss" rel="stylesheet" href="{pyg_light}">
<style>
:root {{ color-scheme: light dark; }}
@media (prefers-color-scheme: dark) {{
  #ghcss {{ content: url({gh_dark}); }}
  #pygcss {{ content: url({pyg_dark}); }}
}}
.gist-file {{ border:1px solid #d0d7de !important; border-radius:6px !important; background:#fff !important; overflow:hidden !important; }}
@media (prefers-color-scheme: dark) {{
  .gist-file {{ border:1px solid #30363d !important; background:#0d1117 !important; }}
}}
.markdown-body {{ padding:16px; }}
</style>
<div class="gist">
  <div class="gist-file" translate="no" data-color-mode="light" data-light-theme="light">
    <div class="gist-data">
      <div class="js-gist-file-update-container js-task-list-container">
        <div class="file my-2">
          <div class="Box-body readme blob p-5 p-xl-6" style="overflow:auto" tabindex="0" role="region" aria-label="{title}">
            <article class="markdown-body entry-content container-lg" itemprop="text">
              {content}
            </article>
          </div>
        </div>
      </div>
    </div>
    <div class="gist-meta">
      <a href="{raw_url}" style="float:right" class="Link--inTextBlock" target="_blank" rel="noopener">view raw</a>
      <a href="{file_url}" class="Link--inTextBlock" target="_blank">{filename}</a>
      hosted on <a class="Link--inTextBlock" href="https://md-embed.grye.org/docs" target="_blank" rel="noopener">MD Embed</a> by <a class="Link--inTextBlock" href="https://github.com/Awerito" target="_blank" rel="noopener">@Awerito</a>
    </div>
  </div>
</div>
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


@app.get("/md/fragment")
async def md_fragment(
    repo: str = Query(...),
    path: str = Query(...),
    ref: str = Query("main"),
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
    file_title = title or os.path.basename(path)
    url_raw = src_url(repo, path, ref)
    url_blob = blob_url(repo, path, ref)

    frag = FRAGMENT_TEMPLATE.format(
        gist_css=GIST_EMBED_CSS,
        gh_light=GITHUB_MARKDOWN_LIGHT,
        gh_dark=GITHUB_MARKDOWN_DARK,
        pyg_light=PYGMENTS_LIGHT,
        pyg_dark=PYGMENTS_DARK,
        content=html_body,
        title=file_title,
        raw_url=url_raw,
        file_url=url_blob,
        filename=file_title,
    )
    et = etag_for(md_text.encode("utf-8"))
    resp = HTMLResponse(content=frag)
    cache_headers(resp, et)
    return resp


@app.get("/md/embed.js")
async def md_embed_js(
    repo: str = Query(...),
    path: str = Query(...),
    ref: str = Query("main"),
    title: str | None = Query(None),
) -> Response:
    frag_resp = await md_fragment(repo=repo, path=path, ref=ref, title=title)
    frag_html = frag_resp.body.decode("utf-8")
    js = f"document.write({frag_html!r});"
    return Response(content=js, media_type="application/javascript")


def parse_github_blob_url(u: str) -> tuple[str, str, str]:
    p = urlparse(u)
    if p.netloc not in {"github.com", "www.github.com"}:
        raise ValueError("unsupported host")
    parts = [s for s in p.path.split("/") if s]
    if len(parts) < 5 or parts[2] != "blob":
        raise ValueError("invalid blob url")
    owner, repo = parts[0], parts[1]
    ref = parts[3]
    relpath = "/".join(parts[4:])
    return f"{owner}/{repo}", relpath, ref


def build_embed_src(
    request: Request, repo: str, path: str, ref: str, title: Optional[str]
) -> str:
    base = (
        PUBLIC_BASE_URL.rstrip("/")
        if PUBLIC_BASE_URL
        else str(request.base_url).rstrip("/")
    )
    q = f"repo={quote(repo)}&path={quote(path)}&ref={quote(ref)}"
    if title:
        q += f"&title={quote(title)}"
    return f"{base}/md/embed.js?{q}"


@app.get("/md/snippet", response_class=PlainTextResponse)
async def md_snippet(
    request: Request,
    url: str = Query(..., description="GitHub blob URL"),
    title: Optional[str] = Query(None),
):
    try:
        repo, path, ref = parse_github_blob_url(url)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not repo_re.match(repo) or not ref_re.match(ref) or not path_re.match(path):
        raise HTTPException(400, "invalid url structure")

    base = (
        PUBLIC_BASE_URL.rstrip("/")
        if PUBLIC_BASE_URL
        else str(request.base_url).rstrip("/")
    )
    q = f"repo={quote(repo)}&path={quote(path)}&ref={quote(ref)}"
    if title:
        q += f"&title={quote(title)}"
    script_tag = f'<script src="{base}/md/embed.js?{q}"></script>'
    return PlainTextResponse(content=script_tag)


@app.get("/raw-url")
def get_raw_url(github_url: str = Query(..., description="GitHub file URL")):
    if "github.com" not in github_url or "/blob/" not in github_url:
        return HTTPException(
            status_code=400,
            detail="Invalid GitHub URL. Must be a GitHub file URL containing '/blob/'.",
        )

    raw_url = github_url.replace("github.com", "raw.githubusercontent.com").replace(
        "/blob/", "/"
    )
    return {"raw_url": raw_url}
