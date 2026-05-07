"""
🎬 Ultimate Video Downloader Bot v2.0
- Koi bhi website
- 6-layer bot detection bypass
- No cookies required
- Auto retry different clients
"""

import os
import random
import time
import threading
import traceback
from pathlib import Path
from typing import Optional, List

import yt_dlp
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ═══════════════════════════════════════════════════
#  App setup
# ═══════════════════════════════════════════════════
app = FastAPI(
    title="Ultimate Video Downloader Bot",
    description="Kisi bhi website se video – 6-layer stealth bypass",
    version="2.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TEMP_DIR = Path("/tmp/vdl_bot")
TEMP_DIR.mkdir(parents=True, exist_ok=True)
FILE_EXPIRY = 300

# ═══════════════════════════════════════════════════
#  Models
# ═══════════════════════════════════════════════════
class InfoRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    video_type: Optional[str] = None

# ═══════════════════════════════════════════════════
#  Rotating User Agents
# ═══════════════════════════════════════════════════
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]

def rand_ua():
    return random.choice(USER_AGENTS)

# ═══════════════════════════════════════════════════
#  6-Layer Strategy System
# ═══════════════════════════════════════════════════
COMMON_OPTS = {
    "quiet":               True,
    "no_warnings":         True,
    "retries":             8,
    "fragment_retries":    8,
    "file_access_retries": 3,
    "geo_bypass":          True,
    "nocheckcertificate":  True,
    "socket_timeout":      30,
}

def build_strategies(extra: dict = None) -> List[dict]:
    ex = extra or {}
    return [
        # Layer 1 – iOS client (best YouTube bypass)
        {**ex,
         "extractor_args": {"youtube": {"player_client": ["ios"]}},
         "http_headers": {"User-Agent": USER_AGENTS[6]}},

        # Layer 2 – Android client
        {**ex,
         "extractor_args": {"youtube": {"player_client": ["android"]}},
         "http_headers": {"User-Agent": USER_AGENTS[5]}},

        # Layer 3 – TV Embedded (no sign-in required)
        {**ex,
         "extractor_args": {"youtube": {"player_client": ["tv_embedded"]}},
         "http_headers": {"User-Agent": rand_ua()}},

        # Layer 4 – mweb client
        {**ex,
         "extractor_args": {"youtube": {"player_client": ["mweb"], "player_skip": ["webpage"]}},
         "http_headers": {"User-Agent": USER_AGENTS[6]}},

        # Layer 5 – Web + full browser headers
        {**ex,
         "extractor_args": {"youtube": {"player_client": ["web"]}},
         "http_headers": {
             "User-Agent":      rand_ua(),
             "Accept-Language": "en-US,en;q=0.9",
             "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
             "Sec-Fetch-Mode":  "navigate",
             "Sec-Fetch-Site":  "none",
             "Sec-Fetch-Dest":  "document",
             "DNT":             "1",
         }},

        # Layer 6 – Generic (non-YouTube sites)
        {**ex,
         "http_headers": {
             "User-Agent":      rand_ua(),
             "Accept-Language": "en-US,en;q=0.9",
             "Referer":         "https://www.google.com/",
             "Accept":          "*/*",
         }},
    ]


def smart_fetch(url: str) -> dict:
    """Multi-strategy info extraction – koi na koi kaam kar dega"""
    strategies = build_strategies()
    last_err = ""
    for i, strat in enumerate(strategies, 1):
        opts = {**COMMON_OPTS, **strat, "skip_download": True}
        try:
            print(f"[FETCH] Layer {i} try...")
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            print(f"[FETCH] Layer {i} SUCCESS")
            return info
        except Exception as e:
            last_err = str(e)
            print(f"[FETCH] Layer {i} fail: {last_err[:80]}")
            time.sleep(0.4)
    raise yt_dlp.utils.DownloadError(f"Sab 6 layers fail: {last_err}")


def smart_download(url: str, fmt_sel: str, out_tmpl: str):
    """Multi-strategy download"""
    dl_extra = {
        "format":              fmt_sel,
        "outtmpl":             out_tmpl,
        "merge_output_format": "mp4",
    }
    strategies = build_strategies(dl_extra)
    last_err = ""
    for i, strat in enumerate(strategies, 1):
        opts = {**COMMON_OPTS, **strat}
        try:
            print(f"[DL] Layer {i} try...")
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            print(f"[DL] Layer {i} SUCCESS")
            return
        except yt_dlp.utils.DownloadError as e:
            last_err = str(e)
            low = last_err.lower()
            # format related error pe aage try karna bekar hai
            if any(x in low for x in ["requested format", "no video formats", "not available"]):
                raise
            print(f"[DL] Layer {i} fail: {last_err[:80]}")
            time.sleep(0.4)
        except Exception as e:
            last_err = str(e)
            print(f"[DL] Layer {i} exception: {last_err[:80]}")
            time.sleep(0.4)
    raise yt_dlp.utils.DownloadError(f"Sab 6 layers fail: {last_err}")

# ═══════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════
def fmt_size(b) -> str:
    if not b: return "Unknown"
    if b < 1024**2: return f"{b/1024:.1f} KB"
    if b < 1024**3: return f"{b/1024**2:.1f} MB"
    return f"{b/1024**3:.2f} GB"

def fmt_dur(sec) -> str:
    if not sec: return "Unknown"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

def get_fmt_str(video_type: Optional[str]) -> str:
    if not video_type:
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    vt = video_type.lower().strip()
    mp = {
        "best":    "bestvideo+bestaudio/best",
        "highest": "bestvideo+bestaudio/best",
        "worst":   "worstvideo+worstaudio/worst",
        "audio":   "bestaudio/best",
        "mp3":     "bestaudio/best",
        "mp4":     "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "webm":    "bestvideo[ext=webm]+bestaudio/best[ext=webm]/best",
        "mkv":     "bestvideo+bestaudio/best",
    }
    if vt in mp: return mp[vt]
    if vt.endswith("p") and vt[:-1].isdigit():
        return f"bestvideo[height<={vt[:-1]}][ext=mp4]+bestaudio[ext=m4a]/best[height<={vt[:-1]}]/best"
    return f"best[format_id={vt}]/best"

def extract_formats(formats: list) -> list:
    result, seen = [], set()
    for f in (formats or []):
        fid = f.get("format_id")
        if not fid or fid in seen: continue
        seen.add(fid)
        hv = f.get("vcodec", "none") not in ("none", None)
        ha = f.get("acodec", "none") not in ("none", None)
        if not hv and not ha: continue
        fsz = f.get("filesize") or f.get("filesize_approx")
        result.append({
            "format_id":  fid,
            "ext":        f.get("ext"),
            "resolution": f.get("resolution") or (f"{f['height']}p" if f.get("height") else "audio only"),
            "filesize":   fmt_size(fsz),
            "filesize_bytes": fsz,
            "has_video":  hv,
            "has_audio":  ha,
            "fps":        f.get("fps"),
        })
    return result

def extract_links(formats: list, video_type: Optional[str] = None) -> list:
    result = []
    for f in (formats or []):
        fu = f.get("url")
        if not fu: continue
        hv = f.get("vcodec", "none") not in ("none", None)
        ha = f.get("acodec", "none") not in ("none", None)
        if not hv and not ha: continue
        fsz = f.get("filesize") or f.get("filesize_approx")

        if video_type:
            vt = video_type.lower().strip()
            if vt.endswith("p") and vt[:-1].isdigit():
                if str(f.get("height", "")) != vt[:-1]: continue
            elif vt in ("audio", "mp3"):
                if hv: continue
            elif vt in ("mp4", "webm", "mkv"):
                if f.get("ext") != vt: continue
            elif vt not in ("best", "highest", "all"):
                if f.get("format_id") != vt: continue

        result.append({
            "format_id":  f.get("format_id"),
            "ext":        f.get("ext"),
            "resolution": f.get("resolution") or (f"{f.get('height')}p" if f.get("height") else "audio only"),
            "filesize":   fmt_size(fsz),
            "has_video":  hv,
            "has_audio":  ha,
            "fps":        f.get("fps"),
            "direct_url": fu,
        })
    return result

def cleanup_old():
    now = time.time()
    for f in TEMP_DIR.iterdir():
        try:
            if f.is_file() and (now - f.stat().st_mtime) > FILE_EXPIRY:
                f.unlink()
        except: pass

def sched_delete(path: str):
    def _r():
        time.sleep(FILE_EXPIRY)
        try:
            if os.path.exists(path): os.remove(path)
        except: pass
    threading.Thread(target=_r, daemon=True).start()

# ═══════════════════════════════════════════════════
#  Routes
# ═══════════════════════════════════════════════════
@app.get("/")
def root():
    return {
        "bot":     "🎬 Ultimate Video Downloader Bot",
        "version": "2.0.0",
        "stealth": "6-layer bypass: ios → android → tv_embedded → mweb → web → generic",
        "endpoints": {
            "GET  /health":         "Server status",
            "POST /video/info":     "Video details + all formats",
            "POST /video/links":    "Direct stream URLs (no server download)",
            "POST /video/download": "File download",
        },
        "video_type": "best | 1080p | 720p | 480p | 360p | mp4 | audio | <format_id>",
    }

@app.get("/health")
def health():
    cleanup_old()
    return {"status": "ok", "version": "2.0.0", "temp_files": len(list(TEMP_DIR.iterdir()))}


@app.post("/video/info")
def video_info(req: InfoRequest):
    cleanup_old()
    try:
        info = smart_fetch(req.url)
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(400, detail=f"Video info nahi mili: {str(e)[:300]}")

    formats = extract_formats(info.get("formats", []))
    desc = (info.get("description") or "").strip()
    return {
        "title":        info.get("title"),
        "uploader":     info.get("uploader"),
        "duration":     fmt_dur(info.get("duration")),
        "duration_sec": info.get("duration"),
        "description":  desc[:600] + ("…" if len(desc) > 600 else ""),
        "thumbnail":    info.get("thumbnail"),
        "view_count":   info.get("view_count"),
        "like_count":   info.get("like_count"),
        "upload_date":  info.get("upload_date"),
        "webpage_url":  info.get("webpage_url"),
        "available_formats": formats,
        "total_formats": len(formats),
    }


@app.post("/video/links")
def video_links(req: DownloadRequest):
    cleanup_old()
    try:
        info = smart_fetch(req.url)
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(400, detail=f"Video info nahi mili: {str(e)[:300]}")

    desc = (info.get("description") or "").strip()
    matched = extract_links(info.get("formats", []), req.video_type)

    if not matched:
        all_links = extract_links(info.get("formats", []))
        return JSONResponse(422, content={
            "error":   f"Format '{req.video_type}' nahi mila",
            "title":   info.get("title"),
            "duration": fmt_dur(info.get("duration")),
            "description": desc[:300] + ("…" if len(desc) > 300 else ""),
            "thumbnail": info.get("thumbnail"),
            "all_available_links": all_links,
            "hint": "in mein se koi format_id ya resolution try karo",
        })

    return {
        "title":          info.get("title"),
        "uploader":       info.get("uploader"),
        "duration":       fmt_dur(info.get("duration")),
        "description":    desc[:300] + ("…" if len(desc) > 300 else ""),
        "thumbnail":      info.get("thumbnail"),
        "requested_type": req.video_type or "best",
        "matched_links":  matched,
        "note": "direct_url browser/player mein open karo",
    }


@app.post("/video/download")
def download_video(req: DownloadRequest, bg: BackgroundTasks):
    cleanup_old()

    try:
        info = smart_fetch(req.url)
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(400, detail=f"Video info nahi mili: {str(e)[:300]}")

    title     = info.get("title", "video")
    safe_name = "".join(c for c in title if c.isalnum() or c in " -_")[:50].strip() or "video"
    fmt_sel   = get_fmt_str(req.video_type)
    out_tmpl  = str(TEMP_DIR / f"{safe_name}_{int(time.time())}.%(ext)s")

    try:
        smart_download(req.url, fmt_sel, out_tmpl)
    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        print(f"[DL FAIL] {err}")
        formats = extract_formats(info.get("formats", []))
        desc = (info.get("description") or "").strip()
        return JSONResponse(422, content={
            "error":    f"Format '{req.video_type}' download nahi hua",
            "reason":   err[:200],
            "title":    title,
            "duration": fmt_dur(info.get("duration")),
            "description": desc[:300] + ("…" if len(desc) > 300 else ""),
            "thumbnail": info.get("thumbnail"),
            "available_formats": formats,
            "hint": "720p, 1080p, best, audio ya koi format_id try karo",
        })
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(500, detail=f"Download error: {str(e)[:200]}")

    downloaded: Optional[Path] = None
    cutoff = time.time() - 180
    for f in sorted(TEMP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and safe_name[:15] in f.name and f.stat().st_mtime > cutoff:
            downloaded = f
            break

    if not downloaded:
        raise HTTPException(500, detail="File nahi mili – dobara try karo")

    sched_delete(str(downloaded))
    file_bytes = downloaded.stat().st_size

    return FileResponse(
        path=str(downloaded),
        filename=downloaded.name,
        media_type="application/octet-stream",
        headers={
            "X-Video-Title": title,
            "X-File-Size":   fmt_size(file_bytes),
            "X-Duration":    fmt_dur(info.get("duration")),
            "X-Expires-In":  "300s",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
