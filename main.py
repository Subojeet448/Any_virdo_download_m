"""
🎬 ULTIMATE VIDEO BOT v4.0 — FINAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ yt-dlp  → 1000+ sites (YouTube, Insta, TikTok …)
✅ Scraper → ANY website (m4movi, pagalworld, etc.)
✅ DuckDuckGo search → har website pe movie dhundho
✅ Iframe follow → player ke andar ka link nikalo
✅ 8-layer bot bypass → jo block kare wha bhi jaao
✅ JW Player / VideoJS / HLS / MP4 sab detect karo
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, re, time, random, threading, traceback
from pathlib import Path
from typing import Optional, List
from urllib.parse import urljoin, urlparse, quote_plus

import httpx
import yt_dlp
from bs4 import BeautifulSoup, SoupStrainer
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ══════════════════════════════════════════
#  App
# ══════════════════════════════════════════
app = FastAPI(
    title="🎬 Ultimate Video Bot",
    description="Kisi bhi website se video — search ya URL",
    version="4.0.0",
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

TEMP_DIR = Path("/tmp/vdl")
TEMP_DIR.mkdir(parents=True, exist_ok=True)
FILE_EXPIRY = 300

# ══════════════════════════════════════════
#  Models
# ══════════════════════════════════════════
class InfoReq(BaseModel):
    url: str

class DlReq(BaseModel):
    url: str
    video_type: Optional[str] = None

class SearchReq(BaseModel):
    query: str
    site: Optional[str] = "youtube"   # youtube | dailymotion | or any domain like m4movi.com
    limit: Optional[int] = 10

class WebSearchReq(BaseModel):
    query: str
    site: Optional[str] = None        # e.g. "m4movi.com" or None for all web
    limit: Optional[int] = 10

class ScrapeReq(BaseModel):
    url: str                           # kisi bhi page ka URL — videos nikalo

# ══════════════════════════════════════════
#  Browser Headers — Real Chrome fingerprint
# ══════════════════════════════════════════
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]

def rua(): return random.choice(UAS)

def bh(referer: str = "https://www.google.com/") -> dict:
    """Full browser headers"""
    return {
        "User-Agent":                rua(),
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language":           "en-US,en;q=0.9,ur;q=0.8",
        "Accept-Encoding":           "gzip, deflate, br",
        "Referer":                   referer,
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "cross-site",
        "Sec-CH-UA":                 '"Chromium";v="124","Google Chrome";v="124"',
        "Sec-CH-UA-Mobile":          "?0",
        "Sec-CH-UA-Platform":        '"Windows"',
        "Upgrade-Insecure-Requests": "1",
        "DNT":                       "1",
        "Connection":                "keep-alive",
        "Cache-Control":             "max-age=0",
    }

# ══════════════════════════════════════════
#  Video URL Patterns — Har player detect karo
# ══════════════════════════════════════════
VID_EXTS   = (r"\.(?:mp4|m3u8|webm|mkv|avi|mov|flv|ts|mpd)(?:[?#][^\s\"'<>]*)?")
CDN_HOSTS  = r"(?:cdn|video|media|stream|player|content|storage|deliver|cache|files?)"

PATTERNS = [
    # Direct file URLs
    rf'(https?://[^\s"\'<>{{}}]+{VID_EXTS})',
    # JW Player / VideoJS / common players
    r'(?:file|src|source|url|stream|video_url|videoUrl|hls_url|mp4)\s*[=:]\s*["\']?(https?://[^"\'\s,;{{}}]+)["\']?',
    # JSON keys
    r'"(?:file|src|url|stream|hls|mp4|dash|source)"\s*:\s*"(https?://[^"]+)"',
    r"'(?:file|src|url|stream|hls|mp4|dash|source)'\s*:\s*'(https?://[^']+)'",
    # data-* attributes
    r'data-(?:src|file|url|video|mp4|hls)\s*=\s*["\']?(https?://[^"\'\s]+)["\']?',
    # embed/object
    r'(?:value|data)\s*=\s*["\']?(https?://[^"\'\s]+\.(?:mp4|m3u8|webm))["\']?',
    # CDN patterns
    rf'(https?://{CDN_HOSTS}[^\s"\'<>]*{VID_EXTS})',
]
COMPILED = [re.compile(p, re.IGNORECASE) for p in PATTERNS]

IFRAME_HOSTS_BLACKLIST = {"google.com", "doubleclick.net", "facebook.com", "twitter.com",
                           "ads.", "analytics", "tracking", "pixel"}

def is_likely_video(url: str) -> bool:
    low = url.lower()
    return any(ext in low for ext in [".mp4", ".m3u8", ".webm", ".mkv", ".ts", ".mpd"])

def extract_urls_from_text(text: str) -> List[str]:
    found = set()
    for pat in COMPILED:
        for m in pat.findall(text):
            u = m if isinstance(m, str) else (m[0] if m else "")
            u = u.strip("'\"").strip()
            if u.startswith("http") and len(u) > 15:
                found.add(u)
    return list(found)

# ══════════════════════════════════════════
#  HTTP Client — real browser simulation
# ══════════════════════════════════════════
def make_client(referer: str = "https://www.google.com/") -> httpx.Client:
    return httpx.Client(
        headers=bh(referer),
        follow_redirects=True,
        timeout=25,
        verify=False,
    )

def fetch_page(url: str, referer: str = "https://www.google.com/") -> str:
    """Page HTML lao — retries ke saath"""
    for attempt in range(3):
        try:
            with make_client(referer) as c:
                r = c.get(url)
                r.raise_for_status()
                return r.text
        except Exception as e:
            if attempt == 2: raise
            time.sleep(1)
    return ""

# ══════════════════════════════════════════
#  Page Scraper — kisi bhi page se videos
# ══════════════════════════════════════════
def scrape_videos_from_page(page_url: str, depth: int = 2) -> List[dict]:
    """
    Kisi bhi page se video URLs nikalo.
    Iframes ke andar bhi jaata hai (depth=2).
    """
    found_videos = {}
    visited      = set()

    def _scrape(url: str, current_depth: int, page_referer: str):
        if url in visited or current_depth < 0:
            return
        visited.add(url)
        print(f"[SCRAPE] depth={current_depth} {url[:80]}")

        try:
            html = fetch_page(url, page_referer)
        except Exception as e:
            print(f"[SCRAPE] fail: {e}")
            return

        # ── 1. Raw regex on full HTML ──
        for u in extract_urls_from_text(html):
            if is_likely_video(u) and u not in found_videos:
                found_videos[u] = {
                    "direct_url":  u,
                    "found_on":    url,
                    "type":        "direct" if ".mp4" in u.lower() else "stream",
                    "ext":         "mp4" if ".mp4" in u.lower() else ("m3u8" if ".m3u8" in u.lower() else "webm"),
                }

        # ── 2. BeautifulSoup parse ──
        try:
            soup = BeautifulSoup(html, "html.parser")

            # <video> / <source> tags
            for tag in soup.find_all(["video", "source", "track"]):
                for attr in ["src", "data-src", "data-url", "data-file"]:
                    val = tag.get(attr, "")
                    if val and val.startswith("http"):
                        full = urljoin(url, val)
                        if is_likely_video(full) and full not in found_videos:
                            found_videos[full] = {
                                "direct_url": full,
                                "found_on":   url,
                                "type":       "video_tag",
                                "ext":        full.split(".")[-1].split("?")[0][:4],
                            }

            # <script> tags — player configs
            for script in soup.find_all("script"):
                sc = script.string or ""
                for u in extract_urls_from_text(sc):
                    if is_likely_video(u) and u not in found_videos:
                        found_videos[u] = {
                            "direct_url": u,
                            "found_on":   url,
                            "type":       "js_player",
                            "ext":        "mp4" if ".mp4" in u.lower() else "m3u8",
                        }

            # <iframe> tags — follow recursively
            if current_depth > 0:
                for iframe in soup.find_all("iframe"):
                    src = iframe.get("src") or iframe.get("data-src") or ""
                    if not src or not src.startswith("http"):
                        src = urljoin(url, src) if src else ""
                    if not src:
                        continue
                    # Skip ad iframes
                    domain = urlparse(src).netloc
                    if any(b in domain for b in IFRAME_HOSTS_BLACKLIST):
                        continue
                    _scrape(src, current_depth - 1, url)

        except Exception as e:
            print(f"[SCRAPE] parse error: {e}")

    _scrape(page_url, depth, "https://www.google.com/")

    return list(found_videos.values())[:30]  # max 30 links


# ══════════════════════════════════════════
#  DuckDuckGo Search — kisi bhi site pe
# ══════════════════════════════════════════
DDG_URLS = [
    "https://html.duckduckgo.com/html/",
    "https://duckduckgo.com/html/",
]

def ddg_search(query: str, site: str = None, limit: int = 10) -> List[dict]:
    """DuckDuckGo se search karo — kisi bhi website pe"""
    q = f"site:{site} {query}" if site else query
    results = []

    for ddg_url in DDG_URLS:
        try:
            with make_client() as c:
                r = c.post(ddg_url, data={"q": q, "b": "", "kl": "wt-wt"})
                soup = BeautifulSoup(r.text, "html.parser")

            for res in soup.find_all("div", class_="result"):
                title_tag = res.find("a", class_="result__a")
                snip_tag  = res.find("a", class_="result__snippet")
                url_tag   = res.find("a", class_="result__url")

                title = title_tag.get_text(strip=True) if title_tag else ""
                link  = title_tag.get("href", "") if title_tag else ""
                snip  = snip_tag.get_text(strip=True)  if snip_tag  else ""
                disp  = url_tag.get_text(strip=True)   if url_tag   else ""

                if link and link.startswith("http") and title:
                    results.append({
                        "title":   title,
                        "url":     link,
                        "snippet": snip,
                        "display_url": disp,
                    })

            if results:
                break  # mila to dobara try mat karo
        except Exception as e:
            print(f"[DDG] fail: {e}")
            continue

    return results[:limit]


# ══════════════════════════════════════════
#  yt-dlp 8-Layer Strategy
# ══════════════════════════════════════════
BASE_YDL = {
    "quiet": True, "no_warnings": True,
    "retries": 10, "fragment_retries": 10,
    "geo_bypass": True, "nocheckcertificate": True,
    "socket_timeout": 30,
}

def _ydl_strategies(extra: dict = None) -> List[dict]:
    ex = extra or {}
    return [
        {**ex, "extractor_args": {"youtube": {"player_client": ["ios"]}},          "http_headers": {"User-Agent": UAS[6]}},
        {**ex, "extractor_args": {"youtube": {"player_client": ["android"]}},      "http_headers": {"User-Agent": UAS[5]}},
        {**ex, "extractor_args": {"youtube": {"player_client": ["tv_embedded"]}},  "http_headers": {"User-Agent": rua()}},
        {**ex, "extractor_args": {"youtube": {"player_client": ["mweb"]}},         "http_headers": {"User-Agent": UAS[6]}},
        {**ex, "extractor_args": {"youtube": {"player_client": ["web"]}},          "http_headers": bh()},
        {**ex, "extractor_args": {"youtube": {"player_client": ["ios", "web"]}},   "http_headers": bh("https://www.youtube.com/")},
        {**ex,                                                                      "http_headers": bh()},
        {**ex,                                                                      "http_headers": {"User-Agent": rua(), "Accept-Language": "en-US,en;q=0.5"}},
    ]

def ydl_fetch(url: str, extra: dict = None) -> dict:
    for i, s in enumerate(_ydl_strategies(extra), 1):
        try:
            print(f"[YDL] Layer {i}/8 ...")
            opts = {**BASE_YDL, **s, "skip_download": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            print(f"[YDL] ✅ Layer {i}")
            return info
        except Exception as e:
            print(f"[YDL] Layer {i} ❌ {str(e)[:60]}")
            time.sleep(0.3)
    raise yt_dlp.utils.DownloadError("Sab 8 layers fail")

def ydl_dl(url: str, fmt: str, out: str):
    ex = {"format": fmt, "outtmpl": out, "merge_output_format": "mp4"}
    for i, s in enumerate(_ydl_strategies(ex), 1):
        try:
            print(f"[DL] Layer {i}/8 ...")
            opts = {**BASE_YDL, **s}
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            print(f"[DL] ✅ Layer {i}")
            return
        except yt_dlp.utils.DownloadError as e:
            msg = str(e).lower()
            if any(x in msg for x in ["requested format", "no video formats"]):
                raise
            print(f"[DL] Layer {i} ❌ {str(e)[:60]}")
            time.sleep(0.3)
        except Exception as e:
            print(f"[DL] Layer {i} exception: {str(e)[:60]}")
            time.sleep(0.3)
    raise yt_dlp.utils.DownloadError("Sab 8 layers fail")

# ══════════════════════════════════════════
#  yt-dlp Supported Search Prefixes
# ══════════════════════════════════════════
YDL_SEARCH = {
    "youtube": "ytsearch{n}:",  "yt": "ytsearch{n}:",
    "dailymotion": "dmsearch{n}:", "dm": "dmsearch{n}:",
    "soundcloud":  "scsearch{n}:", "sc": "scsearch{n}:",
    "bilibili":    "bilisearch{n}:",
}

def is_ydl_site(site: str) -> bool:
    return (site or "").lower().strip() in YDL_SEARCH

# ══════════════════════════════════════════
#  Utilities
# ══════════════════════════════════════════
def fsize(b) -> str:
    if not b: return "?"
    if b < 1024**2: return f"{b/1024:.1f} KB"
    if b < 1024**3: return f"{b/1024**2:.1f} MB"
    return f"{b/1024**3:.2f} GB"

def fdur(s) -> str:
    if not s: return "?"
    s = int(s); h, r = divmod(s, 3600); m, sc = divmod(r, 60)
    return f"{h}h {m}m {sc}s" if h else f"{m}m {sc}s"

def fmt_str(vtype: Optional[str]) -> str:
    if not vtype:
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    vt = vtype.lower().strip()
    MAP = {
        "best": "bestvideo+bestaudio/best", "highest": "bestvideo+bestaudio/best",
        "worst": "worstvideo+worstaudio/worst",
        "audio": "bestaudio/best", "mp3": "bestaudio/best",
        "mp4": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "webm": "bestvideo[ext=webm]+bestaudio/best[ext=webm]/best",
    }
    if vt in MAP: return MAP[vt]
    if vt.endswith("p") and vt[:-1].isdigit():
        return f"bestvideo[height<={vt[:-1]}][ext=mp4]+bestaudio[ext=m4a]/best[height<={vt[:-1]}]/best"
    return f"best[format_id={vt}]/best"

def pick_fmts(formats: list) -> list:
    seen, out = set(), []
    for f in (formats or []):
        fid = f.get("format_id")
        if not fid or fid in seen: continue
        seen.add(fid)
        hv = f.get("vcodec", "none") not in ("none", None)
        ha = f.get("acodec", "none") not in ("none", None)
        if not hv and not ha: continue
        fsz = f.get("filesize") or f.get("filesize_approx")
        out.append({
            "format_id": fid, "ext": f.get("ext"),
            "resolution": f.get("resolution") or (f"{f['height']}p" if f.get("height") else "audio only"),
            "filesize": fsize(fsz), "has_video": hv, "has_audio": ha, "fps": f.get("fps"),
        })
    return out

def pick_links(formats: list, vtype: Optional[str] = None) -> list:
    out = []
    for f in (formats or []):
        fu = f.get("url")
        if not fu: continue
        hv = f.get("vcodec", "none") not in ("none", None)
        ha = f.get("acodec", "none") not in ("none", None)
        if not hv and not ha: continue
        fsz = f.get("filesize") or f.get("filesize_approx")
        if vtype:
            vt = vtype.lower().strip()
            if vt.endswith("p") and vt[:-1].isdigit():
                if str(f.get("height", "")) != vt[:-1]: continue
            elif vt in ("audio", "mp3"):
                if hv: continue
            elif vt in ("mp4", "webm"):
                if f.get("ext") != vt: continue
            elif vt not in ("best", "highest", "all"):
                if f.get("format_id") != vt: continue
        out.append({
            "format_id": f.get("format_id"), "ext": f.get("ext"),
            "resolution": f.get("resolution") or (f"{f.get('height')}p" if f.get("height") else "audio only"),
            "filesize": fsize(fsz), "has_video": hv, "has_audio": ha,
            "fps": f.get("fps"), "direct_url": fu,
        })
    return out

def cleanup():
    now = time.time()
    for f in TEMP_DIR.iterdir():
        try:
            if f.is_file() and (now - f.stat().st_mtime) > FILE_EXPIRY: f.unlink()
        except: pass

def sched_del(path: str):
    def _r():
        time.sleep(FILE_EXPIRY)
        try:
            if os.path.exists(path): os.remove(path)
        except: pass
    threading.Thread(target=_r, daemon=True).start()

# ══════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════
@app.get("/")
def root():
    return {
        "bot": "🎬 Ultimate Video Bot", "version": "4.0.0",
        "power": "yt-dlp (1000+ sites) + Web Scraper (ANY site) + DuckDuckGo Search",
        "endpoints": {
            "POST /search":      "yt-dlp sites pe search (YouTube, DM, SC, Bilibili)",
            "POST /search/web":  "🌐 KISI BHI website pe search (m4movi, pagalworld etc.)",
            "POST /scrape":      "🔍 Kisi bhi page URL se video links nikalo",
            "POST /video/info":  "URL → details + formats",
            "POST /video/links": "URL → direct stream URLs",
            "POST /video/download": "URL → file download",
        },
        "search_web_sites": "m4movi.com | pagalworld.com | filmyzilla.com | ya koi bhi website",
    }

@app.get("/health")
def health():
    cleanup()
    return {"status": "ok", "version": "4.0.0"}


# ─────────────────────────────────────
#  🔍 yt-dlp Search (YouTube etc.)
# ─────────────────────────────────────
@app.post("/search")
def ydl_search(req: SearchReq):
    cleanup()
    site = (req.site or "youtube").lower().strip()
    n    = min(max(req.limit or 10, 1), 10)

    # yt-dlp supported site
    if is_ydl_site(site):
        prefix = YDL_SEARCH[site].replace("{n}", str(n))
        url    = f"{prefix}{req.query}"
    else:
        # unsupported → redirect to /search/web
        return JSONResponse(307, content={
            "message": f"'{site}' yt-dlp mein nahi hai — /search/web use karo",
            "redirect": "/search/web",
            "body": {"query": req.query, "site": site},
        })

    try:
        raw = ydl_fetch(url, {"extract_flat": False})
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(400, detail=f"Search fail: {str(e)[:300]}")

    entries = raw.get("entries") or ([raw] if raw.get("title") else [])
    if not entries:
        raise HTTPException(404, detail=f"'{req.query}' ka koi nateeja nahi mila")

    results = []
    for i, e in enumerate(entries[:n], 1):
        if not e: continue
        fmts  = e.get("formats") or []
        desc  = (e.get("description") or "").strip()
        results.append({
            "rank": i,
            "title":        e.get("title"),
            "url":          e.get("webpage_url") or e.get("url"),
            "duration":     fdur(e.get("duration")),
            "uploader":     e.get("uploader"),
            "view_count":   e.get("view_count"),
            "thumbnail":    e.get("thumbnail"),
            "description":  desc[:200] + ("…" if len(desc) > 200 else ""),
            "download_links": pick_links(fmts),
            "available_formats": pick_fmts(fmts),
        })

    return {"query": req.query, "site": site, "total": len(results), "results": results}


# ─────────────────────────────────────
#  🌐 Web Search — KISI BHI Website
# ─────────────────────────────────────
@app.post("/search/web")
def web_search_endpoint(req: WebSearchReq):
    """
    DuckDuckGo se search karo + har result page se video links nikalo.
    m4movi.com ya koi bhi website — sab pe kaam karta hai.
    """
    cleanup()
    n    = min(max(req.limit or 10, 1), 10)
    site = (req.site or "").strip()

    print(f"[WEB SEARCH] query='{req.query}' site='{site}'")

    # ── DuckDuckGo search ──
    try:
        search_results = ddg_search(req.query, site or None, n * 2)
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(400, detail=f"DuckDuckGo search fail: {str(e)[:200]}")

    if not search_results:
        raise HTTPException(404, detail=f"'{req.query}' ka koi nateeja nahi mila")

    # ── Har result se video links nikalo ──
    final_results = []
    for i, res in enumerate(search_results[:n], 1):
        page_url = res["url"]
        print(f"[WEB SEARCH] Scraping result {i}: {page_url[:60]}")

        videos = []

        # 1st: yt-dlp se try karo
        try:
            info  = ydl_fetch(page_url)
            fmts  = info.get("formats") or []
            videos = pick_links(fmts)
            if not videos:
                # try scraper
                videos = scrape_videos_from_page(page_url)
        except Exception:
            # yt-dlp ne nahi kiya → scraper use karo
            try:
                videos = scrape_videos_from_page(page_url)
            except Exception as e:
                print(f"[SCRAPE FAIL] {e}")
                videos = []

        entry = {
            "rank":         i,
            "title":        res["title"],
            "url":          page_url,
            "display_url":  res.get("display_url", ""),
            "snippet":      res.get("snippet", ""),
            "video_links":  videos,
            "videos_found": len(videos),
        }
        final_results.append(entry)

    total_videos = sum(r["videos_found"] for r in final_results)

    return {
        "query":         req.query,
        "site_filter":   site or "all web",
        "pages_searched": len(final_results),
        "total_videos_found": total_videos,
        "results":       final_results,
        "hint": "har result ka 'url' leke /scrape mein do full video extraction ke liye",
    }


# ─────────────────────────────────────
#  🔎 Scrape — Kisi bhi Page se Video
# ─────────────────────────────────────
@app.post("/scrape")
def scrape_page(req: ScrapeReq):
    """
    Kisi bhi website/page ka URL do → sare video links nikalo.
    Iframes ke andar bhi jaata hai, JS players bhi detect karta hai.
    """
    cleanup()

    # Pehle yt-dlp try karo
    ydl_links = []
    ydl_info  = {}
    try:
        info     = ydl_fetch(req.url)
        fmts     = info.get("formats") or []
        ydl_links = pick_links(fmts)
        ydl_info  = {
            "title":    info.get("title"),
            "duration": fdur(info.get("duration")),
            "uploader": info.get("uploader"),
            "thumbnail": info.get("thumbnail"),
        }
    except Exception as e:
        print(f"[SCRAPE] yt-dlp fail: {str(e)[:80]}")

    # Web scraper se bhi nikalo
    scraped_links = []
    try:
        scraped_links = scrape_videos_from_page(req.url, depth=2)
    except Exception as e:
        print(f"[SCRAPE] web scraper fail: {str(e)[:80]}")

    # Combine — unique rakho
    all_urls = {l["direct_url"] for l in ydl_links}
    for s in scraped_links:
        if s["direct_url"] not in all_urls:
            ydl_links.append(s)
            all_urls.add(s["direct_url"])

    if not ydl_links:
        raise HTTPException(404, detail="Koi video link nahi mila is page se")

    return {
        "page_url":     req.url,
        "title":        ydl_info.get("title", ""),
        "duration":     ydl_info.get("duration", ""),
        "thumbnail":    ydl_info.get("thumbnail", ""),
        "total_links":  len(ydl_links),
        "video_links":  ydl_links,
    }


# ─────────────────────────────────────
#  📋 Video Info
# ─────────────────────────────────────
@app.post("/video/info")
def video_info(req: InfoReq):
    cleanup()
    try:
        info = ydl_fetch(req.url)
    except Exception as e:
        raise HTTPException(400, detail=f"Info nahi mili: {str(e)[:300]}")
    fmts = pick_fmts(info.get("formats", []))
    desc = (info.get("description") or "").strip()
    return {
        "title": info.get("title"), "uploader": info.get("uploader"),
        "url": info.get("webpage_url"),
        "duration": fdur(info.get("duration")), "duration_sec": info.get("duration"),
        "description": desc[:600] + ("…" if len(desc) > 600 else ""),
        "thumbnail": info.get("thumbnail"),
        "view_count": info.get("view_count"), "like_count": info.get("like_count"),
        "upload_date": info.get("upload_date"),
        "available_formats": fmts, "total_formats": len(fmts),
    }


# ─────────────────────────────────────
#  🔗 Direct Links
# ─────────────────────────────────────
@app.post("/video/links")
def video_links(req: DlReq):
    cleanup()
    try:
        info = ydl_fetch(req.url)
    except Exception as e:
        raise HTTPException(400, detail=f"Info nahi mili: {str(e)[:300]}")
    desc  = (info.get("description") or "").strip()
    links = pick_links(info.get("formats", []), req.video_type)
    if not links:
        all_l = pick_links(info.get("formats", []))
        return JSONResponse(422, content={
            "error": f"Format '{req.video_type}' nahi mila",
            "title": info.get("title"), "url": info.get("webpage_url"),
            "duration": fdur(info.get("duration")),
            "description": desc[:300] + ("…" if len(desc) > 300 else ""),
            "thumbnail": info.get("thumbnail"),
            "all_available_links": all_l,
        })
    return {
        "title": info.get("title"), "url": info.get("webpage_url"),
        "uploader": info.get("uploader"), "duration": fdur(info.get("duration")),
        "description": desc[:300] + ("…" if len(desc) > 300 else ""),
        "thumbnail": info.get("thumbnail"),
        "requested_type": req.video_type or "all",
        "download_links": links,
    }


# ─────────────────────────────────────
#  ⬇ File Download
# ─────────────────────────────────────
@app.post("/video/download")
def download_video(req: DlReq, bg: BackgroundTasks):
    cleanup()
    try:
        info = ydl_fetch(req.url)
    except Exception as e:
        raise HTTPException(400, detail=f"Info nahi mili: {str(e)[:300]}")

    title    = info.get("title", "video")
    safe     = "".join(c for c in title if c.isalnum() or c in " -_")[:50].strip() or "video"
    sel      = fmt_str(req.video_type)
    out_tmpl = str(TEMP_DIR / f"{safe}_{int(time.time())}.%(ext)s")

    try:
        ydl_dl(req.url, sel, out_tmpl)
    except yt_dlp.utils.DownloadError as e:
        fmts = pick_fmts(info.get("formats", []))
        desc = (info.get("description") or "").strip()
        return JSONResponse(422, content={
            "error": f"Format '{req.video_type}' fail", "reason": str(e)[:200],
            "title": title, "url": info.get("webpage_url"),
            "duration": fdur(info.get("duration")),
            "description": desc[:300] + ("…" if len(desc) > 300 else ""),
            "thumbnail": info.get("thumbnail"),
            "available_formats": fmts,
            "hint": "720p | 1080p | best | audio | mp4 try karo",
        })
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(500, detail=f"Download error: {str(e)[:200]}")

    downloaded: Optional[Path] = None
    cutoff = time.time() - 180
    for f in sorted(TEMP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and safe[:15] in f.name and f.stat().st_mtime > cutoff:
            downloaded = f; break

    if not downloaded:
        raise HTTPException(500, detail="File nahi mili — dobara try karo")

    sched_del(str(downloaded))
    fbytes = downloaded.stat().st_size

    return FileResponse(
        path=str(downloaded), filename=downloaded.name,
        media_type="application/octet-stream",
        headers={
            "X-Video-Title": title, "X-Video-URL": info.get("webpage_url", ""),
            "X-File-Size": fsize(fbytes), "X-Duration": fdur(info.get("duration")),
            "X-Expires-In": "300s", "X-Bot-Version": "4.0-stealth",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
