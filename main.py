import os
import time
import threading
import traceback
from pathlib import Path
from typing import Optional

import yt_dlp
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─────────────────────────────────────────────
#  App Setup
# ─────────────────────────────────────────────
app = FastAPI(
    title="🎬 Video Downloader Bot",
    description="Kisi bhi website se video download karo – FastAPI ke zariye",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = Path("/tmp/vdl_bot")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

FILE_EXPIRY_SEC = 300  # 5 minutes


# ─────────────────────────────────────────────
#  Request Models
# ─────────────────────────────────────────────
class InfoRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    video_type: Optional[str] = None  # e.g. "720p", "1080p", "mp4", "best", "audio"


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
def format_size(b) -> str:
    if not b:
        return "Unknown"
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} MB"
    return f"{b / 1024 ** 3:.2f} GB"


def format_duration(sec) -> str:
    if not sec:
        return "Unknown"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"


def is_bot_allowed(url: str) -> bool:
    """robots.txt check – agar bot allowed nahi to False return karega."""
    try:
        from urllib.parse import urlparse
        from urllib.robotparser import RobotFileParser
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch("*", url)
    except Exception:
        return True  # check fail hua to allowed maan lo


def cleanup_old_files():
    """5 minute se purane temp files delete karo."""
    now = time.time()
    for f in TEMP_DIR.iterdir():
        try:
            if f.is_file() and (now - f.stat().st_mtime) > FILE_EXPIRY_SEC:
                f.unlink()
        except Exception:
            pass


def schedule_delete(filepath: str):
    """Background thread – 5 minute baad file delete karega."""
    def _run():
        time.sleep(FILE_EXPIRY_SEC)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
    t = threading.Thread(target=_run, daemon=True)
    t.start()


def get_ydl_format(video_type: Optional[str]) -> str:
    if not video_type:
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    vt = video_type.lower().strip()
    mapping = {
        "best":    "bestvideo+bestaudio/best",
        "highest": "bestvideo+bestaudio/best",
        "worst":   "worstvideo+worstaudio/worst",
        "lowest":  "worstvideo+worstaudio/worst",
        "audio":   "bestaudio/best",
        "mp3":     "bestaudio/best",
        "mp4":     "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "webm":    "bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best",
    }
    if vt in mapping:
        return mapping[vt]
    # "720p", "1080p" etc.
    if vt.endswith("p") and vt[:-1].isdigit():
        h = vt[:-1]
        return f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}]/best"
    # koi specific format_id
    return f"best[format_id={vt}]/bestvideo[format_id={vt}]+bestaudio/best"


def extract_formats(formats: list) -> list:
    result = []
    seen = set()
    for f in (formats or []):
        key = f.get("format_id")
        if not key or key in seen:
            continue
        seen.add(key)
        has_video = f.get("vcodec", "none") not in ("none", None)
        has_audio = f.get("acodec", "none") not in ("none", None)
        if not has_video and not has_audio:
            continue
        fsize = f.get("filesize") or f.get("filesize_approx")
        result.append({
            "format_id":  f.get("format_id"),
            "ext":        f.get("ext"),
            "resolution": f.get("resolution") or (f"{f['height']}p" if f.get("height") else "audio only"),
            "filesize":   format_size(fsize),
            "filesize_bytes": fsize,
            "has_video":  has_video,
            "has_audio":  has_audio,
            "fps":        f.get("fps"),
            "vcodec":     f.get("vcodec"),
            "acodec":     f.get("acodec"),
        })
    return result


def fetch_info(url: str) -> dict:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "bot": "🎬 Video Downloader Bot",
        "version": "1.0.0",
        "endpoints": {
            "GET  /":               "Ye page",
            "GET  /health":         "Health check",
            "POST /video/info":     "Video ki details + available formats",
            "POST /video/links":    "Direct video URLs do (file download nahi hogi)",
            "POST /video/download": "Video file server pe download karke do",
        },
        "usage": {
            "url":        "required – website URL",
            "video_type": "optional – best | 720p | 1080p | mp4 | audio | <format_id>",
        },
    }


@app.get("/health")
def health():
    cleanup_old_files()
    return {"status": "ok", "temp_files": len(list(TEMP_DIR.iterdir()))}


@app.post("/video/info")
def video_info(req: InfoRequest):
    """
    Video ki puri detail – title, description, duration, filesize, formats.
    """
    cleanup_old_files()

    if not is_bot_allowed(req.url):
        raise HTTPException(
            status_code=403,
            detail="❌ Is website par bot allowed nahi hai. Download possible nahi."
        )

    try:
        info = fetch_info(req.url)
    except yt_dlp.utils.DownloadError as e:
        print(f"[INFO ERROR] {e}")
        raise HTTPException(status_code=400, detail=f"URL se info nahi mili: {str(e)}")
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

    formats = extract_formats(info.get("formats", []))
    desc = (info.get("description") or "").strip()

    return {
        "title":       info.get("title"),
        "uploader":    info.get("uploader"),
        "duration":    format_duration(info.get("duration")),
        "duration_sec": info.get("duration"),
        "description": desc[:600] + ("…" if len(desc) > 600 else ""),
        "thumbnail":   info.get("thumbnail"),
        "view_count":  info.get("view_count"),
        "like_count":  info.get("like_count"),
        "upload_date": info.get("upload_date"),
        "webpage_url": info.get("webpage_url"),
        "available_formats": formats,
        "total_formats": len(formats),
    }


@app.post("/video/links")
def video_links(req: DownloadRequest):
    """
    Direct video URLs do – file download nahi hogi.
    Browser ya player mein directly play ho sakta hai.
    """
    cleanup_old_files()

    if not is_bot_allowed(req.url):
        raise HTTPException(
            status_code=403,
            detail="❌ Is website par bot allowed nahi hai."
        )

    try:
        info = fetch_info(req.url)
    except yt_dlp.utils.DownloadError as e:
        print(f"[LINKS ERROR] {e}")
        raise HTTPException(status_code=400, detail=f"URL se info nahi mili: {str(e)}")
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

    all_formats = info.get("formats", []) or []
    fmt_sel = get_ydl_format(req.video_type)

    # requested format ka URL dhundho
    matched = []
    for f in all_formats:
        fu = f.get("url")
        if not fu:
            continue
        fsize = f.get("filesize") or f.get("filesize_approx")
        has_video = f.get("vcodec", "none") not in ("none", None)
        has_audio = f.get("acodec", "none") not in ("none", None)

        # filter by video_type
        if req.video_type:
            vt = req.video_type.lower().strip()
            if vt.endswith("p") and vt[:-1].isdigit():
                if str(f.get("height", "")) != vt[:-1]:
                    continue
            elif vt in ("audio", "mp3"):
                if has_video:
                    continue
            elif vt in ("mp4", "webm"):
                if f.get("ext") != vt:
                    continue
            elif vt not in ("best", "highest"):
                if f.get("format_id") != vt:
                    continue

        matched.append({
            "format_id":  f.get("format_id"),
            "ext":        f.get("ext"),
            "resolution": f.get("resolution") or (f"{f.get('height')}p" if f.get("height") else "audio only"),
            "filesize":   format_size(fsize),
            "filesize_bytes": fsize,
            "has_video":  has_video,
            "has_audio":  has_audio,
            "fps":        f.get("fps"),
            "direct_url": fu,
        })

    # agar koi match nahi mila to sab do
    if not matched:
        all_links = []
        for f in all_formats:
            fu = f.get("url")
            if not fu:
                continue
            fsize = f.get("filesize") or f.get("filesize_approx")
            has_video = f.get("vcodec", "none") not in ("none", None)
            has_audio = f.get("acodec", "none") not in ("none", None)
            if not has_video and not has_audio:
                continue
            all_links.append({
                "format_id":  f.get("format_id"),
                "ext":        f.get("ext"),
                "resolution": f.get("resolution") or (f"{f.get('height')}p" if f.get("height") else "audio only"),
                "filesize":   format_size(fsize),
                "has_video":  has_video,
                "has_audio":  has_audio,
                "direct_url": fu,
            })

        desc = (info.get("description") or "").strip()
        return JSONResponse(
            status_code=422,
            content={
                "error":   f"Requested format '{req.video_type}' nahi mila.",
                "title":   info.get("title"),
                "duration": format_duration(info.get("duration")),
                "description": desc[:400] + ("…" if len(desc) > 400 else ""),
                "thumbnail": info.get("thumbnail"),
                "all_available_links": all_links,
                "hint": "Neeche diye direct_url ko browser mein open karo ya downloader mein do",
            },
        )

    desc = (info.get("description") or "").strip()
    return {
        "title":       info.get("title"),
        "uploader":    info.get("uploader"),
        "duration":    format_duration(info.get("duration")),
        "description": desc[:400] + ("…" if len(desc) > 400 else ""),
        "thumbnail":   info.get("thumbnail"),
        "requested_type": req.video_type or "default best",
        "matched_links": matched,
        "note": "Ye direct URLs hain – browser ya player mein directly play honge. Kuch URLs expire ho sakte hain.",
    }


@app.post("/video/download")
def download_video(req: DownloadRequest, bg: BackgroundTasks):
    """
    Video download karo.
    - Agar requested type nahi mila → video details + available formats return karega
    - File 5 minute baad auto-delete ho jaye gi
    """
    cleanup_old_files()

    # ── Bot check ──
    if not is_bot_allowed(req.url):
        raise HTTPException(
            status_code=403,
            detail="❌ Is website par bot allowed nahi hai."
        )

    # ── Video info pehle lo ──
    try:
        info = fetch_info(req.url)
    except yt_dlp.utils.DownloadError as e:
        print(f"[DL INFO ERROR] {e}")
        raise HTTPException(status_code=400, detail=f"URL se info nahi mili: {str(e)}")
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

    title     = info.get("title", "video")
    safe_name = "".join(c for c in title if c.isalnum() or c in " -_")[:60].strip()
    fmt_sel   = get_ydl_format(req.video_type)
    out_tmpl  = str(TEMP_DIR / f"{safe_name}_{int(time.time())}.%(ext)s")

    ydl_opts = {
        "format":      fmt_sel,
        "outtmpl":     out_tmpl,
        "quiet":       True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }

    # ── Download try karo ──
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([req.url])
    except yt_dlp.utils.DownloadError as e:
        err_str = str(e)
        print(f"[DL ERROR] {err_str}")

        # Requested format nahi mila – info return karo
        formats = extract_formats(info.get("formats", []))
        desc = (info.get("description") or "").strip()

        return JSONResponse(
            status_code=422,
            content={
                "error":    f"Requested format '{req.video_type}' nahi mila.",
                "reason":   err_str[:300],
                "title":    title,
                "duration": format_duration(info.get("duration")),
                "description": desc[:400] + ("…" if len(desc) > 400 else ""),
                "thumbnail": info.get("thumbnail"),
                "available_formats": formats,
                "hint": "Neeche diye gaye format_id ya resolution try karo (e.g. '720p', '1080p', 'best', 'audio')",
            },
        )
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Download error: {str(e)}")

    # ── Downloaded file dhundho ──
    downloaded: Optional[Path] = None
    cutoff = time.time() - 120  # last 2 min mein bani file
    for f in sorted(TEMP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and safe_name[:20] in f.name and f.stat().st_mtime > cutoff:
            downloaded = f
            break

    if not downloaded:
        raise HTTPException(status_code=500, detail="Download hua par file nahi mili. Dobara try karo.")

    # ── 5 min baad delete schedule ──
    schedule_delete(str(downloaded))

    file_bytes = downloaded.stat().st_size

    return FileResponse(
        path=str(downloaded),
        filename=downloaded.name,
        media_type="video/mp4",
        headers={
            "X-Video-Title":    title,
            "X-File-Size":      format_size(file_bytes),
            "X-Duration":       format_duration(info.get("duration")),
            "X-Format-Used":    fmt_sel,
            "X-Expires-In":     "300 seconds (5 minutes)",
            "X-Auto-Cleanup":   "yes",
        },
    )


# ─────────────────────────────────────────────
#  Vercel / Local entry
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
