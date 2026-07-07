#!/usr/bin/env python3
"""
Web UI + API for downloading from SoundCloud, Spotify, and YouTube.

- SoundCloud / YouTube: yt-dlp (Python API) with rate-limit backoff and
  progress hooks.
- Spotify: spotdl subprocess (matches tracks via YouTube Music).
- Playlists (more than one file) are compressed into a single .7z archive.
"""

import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

import py7zr
import yt_dlp
from flask import Flask, jsonify, request, send_file

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="static", static_url_path="")

# job_id -> state dict, guarded by JOBS_LOCK for cross-thread updates
JOBS = {}
JOBS_LOCK = threading.Lock()

AUDIO_FORMATS = ("flac", "wav")
RESOLUTIONS = (144, 240, 360, 480, 720, 1080, 1440, 2160)

SOURCE_PATTERNS = {
    "soundcloud": re.compile(r"(^|\.)soundcloud\.com", re.I),
    "spotify": re.compile(r"(^|\.)spotify\.com", re.I),
    "youtube": re.compile(r"(^|\.)(youtube\.com|youtu\.be|music\.youtube\.com)", re.I),
}


def detect_source(url: str) -> str | None:
    match = re.match(r"https?://([^/]+)", url.strip())
    if not match:
        return None
    host = match.group(1)
    for source, pattern in SOURCE_PATTERNS.items():
        if pattern.search(host):
            return source
    return None


def friendly_error(raw: str) -> str:
    """Translate raw downloader errors into messages a user can act on."""
    text = raw or ""
    checks = [
        (r"DRM", "This track is DRM-protected (major-label content served with encrypted streams). It cannot be downloaded — try the artist's independent releases or another upload."),
        (r"429|rate.?limit","The service is rate-limiting us right now. The downloader already retried with increasing delays — wait a few minutes and try again."),
        (r"HTTP Error 401|not authorized|login required|private", "This file is private or requires a login, so it can't be downloaded."),
        (r"HTTP Error 403|forbidden|geo.?(restrict|block)", "Access to this file is blocked (region-locked or forbidden by the platform)."),
        (r"HTTP Error 404|not found|does not exist|unavailable", "This file was not found — the link may be dead, deleted, or mistyped."),
        (r"HTTP Error 4\d\d", "The platform rejected the request (client error). Check that the link is correct and publicly accessible."),
        (r"HTTP Error 5\d\d", "The platform's servers are having problems. This is on their side — try again later."),
        (r"Unsupported URL", "This link isn't a downloadable track, playlist, or video."),
        (r"ffmpeg", "Audio conversion failed — make sure ffmpeg is installed on the server."),
        (r"network|timed? ?out|connection", "Network problem while downloading. Check the server's connection and try again."),
    ]
    for pattern, message in checks:
        if re.search(pattern, text, re.I):
            return message
    return f"This file could not be downloaded. Details: {text[:300]}"


def update_job(job_id: str, **fields) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(fields)


class TrackErrorLogger:
    """Collects per-track errors so a playlist keeps going past bad tracks."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.errors: list[str] = []
        self.raw: list[str] = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        print(f"[job {self.job_id}] track error: {msg}", flush=True)
        self.raw.append(str(msg))
        self.errors.append(friendly_error(str(msg)))
        update_job(self.job_id, skipped=list(self.errors))


def make_progress_hook(job_id: str):
    def hook(d):
        info = d.get("info_dict") or {}
        index = info.get("playlist_index")
        count = info.get("n_entries")
        track = info.get("title") or ""

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0.0
            if index and count:
                percent = ((index - 1) + frac) / count * 100
                label = f"Track {index} of {count} — {track}"
            else:
                percent = frac * 100
                label = track
            update_job(job_id, percent=round(percent, 1), message=label)
        elif d["status"] == "finished":
            update_job(job_id, message=f"Converting — {track}")

    return hook


def archive_if_playlist(job_id: str, job_dir: Path) -> Path:
    """Return a single deliverable: the file itself, or a .7z for playlists."""
    files = sorted(p for p in job_dir.rglob("*") if p.is_file())
    if not files:
        raise RuntimeError("Nothing was downloaded.")
    if len(files) == 1:
        return files[0]

    update_job(job_id, status="archiving", percent=None,
               message=f"Compressing {len(files)} files into a .7z archive…")
    archive_path = job_dir / "playlist.7z"
    with py7zr.SevenZipFile(archive_path, "w") as archive:
        for f in files:
            archive.write(f, f.relative_to(job_dir).as_posix())
    for f in files:
        f.unlink()
    return archive_path


def build_ytdlp_options(job_id: str, job_dir: Path, mode: str,
                        audio_format: str, min_res: int, max_res: int) -> dict:
    options = {
        "outtmpl": str(job_dir / "%(playlist_index&{} - |)s%(title)s.%(ext)s"),
        "ignoreerrors": True,        # keep going when one playlist track fails
        "noplaylist": False,
        "logger": TrackErrorLogger(job_id),
        "progress_hooks": [make_progress_hook(job_id)],
        # Rate-limit resilience: retry all HTTP/extractor failures with
        # exponential backoff and pace requests so we avoid 429s entirely.
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "retry_sleep_functions": {
            "http": lambda n: min(5 * (2 ** n), 120),
            "fragment": lambda n: min(5 * (2 ** n), 120),
            "extractor": lambda n: min(5 * (2 ** n), 120),
        },
        "sleep_interval_requests": 1.5,
        # Pause between tracks so playlist downloads don't trip rate limits
        # (hosting providers' shared IPs get throttled much faster than home IPs)
        "sleep_interval": 3,
        "max_sleep_interval": 8,
        "concurrent_fragment_downloads": 1,
    }
    # Optional cookies lift YouTube's "confirm you're not a bot" checks that
    # datacenter IPs often hit. Set YTDLP_COOKIES to a cookies.txt path.
    cookies = os.environ.get("YTDLP_COOKIES")
    if cookies and Path(cookies).is_file():
        options["cookiefile"] = cookies
    if mode == "audio":
        options["format"] = "bestaudio/best"
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_format,
            "preferredquality": "0",
        }]
    else:
        options["format"] = (
            f"bestvideo[height<={max_res}][height>={min_res}]+bestaudio/"
            f"best[height<={max_res}]/best"
        )
        options["merge_output_format"] = "mp4"
    return options


def run_ytdlp_job(job_id: str, url: str, job_dir: Path, mode: str,
                  audio_format: str, min_res: int, max_res: int) -> None:
    options = build_ytdlp_options(job_id, job_dir, mode, audio_format,
                                  min_res, max_res)
    logger = options["logger"]
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])
    # ignoreerrors swallows per-track failures; if nothing at all was
    # downloaded, surface the first real error instead of a generic message.
    if not any(p.is_file() for p in job_dir.rglob("*")) and logger.raw:
        raise RuntimeError(logger.raw[0])


def run_spotify_job(job_id: str, url: str, job_dir: Path,
                    audio_format: str) -> None:
    if shutil.which("spotdl") is None:
        raise RuntimeError("spotdl is not installed on the server. Run: pip install spotdl")
    update_job(job_id, percent=None,
               message="Matching Spotify tracks via YouTube Music…")
    cmd = [
        "spotdl", "download", url,
        "--format", audio_format,
        "--output", str(job_dir / "{list-position} - {artist} - {title}.{output-ext}"),
        "--max-retries", "8",
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    downloaded = 0
    for line in process.stdout:
        line = line.strip()
        if line.startswith("Downloaded"):
            downloaded += 1
            update_job(job_id, message=f"{downloaded} tracks downloaded — {line[12:90]}")
    process.wait()
    has_files = any(p.is_file() for p in job_dir.rglob("*"))
    if process.returncode != 0 and not has_files:
        raise RuntimeError("spotdl failed — the playlist may be private, empty, or Spotify is rate-limiting. Try again in a few minutes.")


def run_job(job_id: str, url: str, source: str, mode: str,
            audio_format: str, min_res: int, max_res: int) -> None:
    job_dir = DOWNLOADS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        update_job(job_id, status="downloading", message="Starting download…")
        if source == "spotify":
            run_spotify_job(job_id, url, job_dir, audio_format)
        else:
            run_ytdlp_job(job_id, url, job_dir, mode, audio_format,
                          min_res, max_res)
        deliverable = archive_if_playlist(job_id, job_dir)
        update_job(job_id, status="done", percent=100,
                   message="Ready to save.", filename=deliverable.name,
                   path=str(deliverable))
    except Exception as exc:  # surfaced to the UI as a clear message
        import traceback
        print(f"[job {job_id}] failed: {exc}\n{traceback.format_exc()}", flush=True)
        update_job(job_id, status="error", error=friendly_error(str(exc)))
        shutil.rmtree(job_dir, ignore_errors=True)


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.post("/api/download")
def start_download():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    mode = data.get("mode", "audio")
    audio_format = data.get("audio_format", "flac")
    min_res = int(data.get("min_res", 360))
    max_res = int(data.get("max_res", 1080))

    if not url:
        return jsonify(error="Paste a link first."), 400
    source = detect_source(url)
    if source is None:
        return jsonify(error="That link isn't from SoundCloud, Spotify, or YouTube."), 400
    if mode not in ("audio", "video"):
        return jsonify(error="Mode must be audio or video."), 400
    if audio_format not in AUDIO_FORMATS:
        return jsonify(error="Format must be FLAC or WAV."), 400
    if min_res not in RESOLUTIONS or max_res not in RESOLUTIONS or min_res > max_res:
        return jsonify(error="Invalid resolution range."), 400
    if source == "spotify" and mode == "video":
        return jsonify(error="Spotify only supports audio downloads."), 400

    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "queued", "percent": 0, "message": "Queued…",
            "error": None, "filename": None, "skipped": [],
        }
    threading.Thread(
        target=run_job,
        args=(job_id, url, source, mode, audio_format, min_res, max_res),
        daemon=True,
    ).start()
    return jsonify(job_id=job_id, source=source)


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return jsonify(error="Unknown job."), 404
        public = {k: v for k, v in job.items() if k != "path"}
    return jsonify(public)


@app.get("/api/jobs/<job_id>/file")
def job_file(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        return jsonify(error="File not ready."), 404
    return send_file(job["path"], as_attachment=True,
                     download_name=job["filename"])


if __name__ == "__main__":
    # 0.0.0.0 so Docker/Railway can expose it; PORT is set by hosting platforms
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
