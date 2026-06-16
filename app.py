import os
import re
import shutil
import subprocess
import threading
import time
import uuid

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")

PASSWORD = os.environ.get("APP_PASSWORD", "changeme")
DOWNLOADS_DIR = "downloads"
JOBS = {}

SOUNDCLOUD_RE = re.compile(r"soundcloud\.com", re.IGNORECASE)
SPOTIFY_RE = re.compile(r"open\.spotify\.com", re.IGNORECASE)
SUPPORTED_FORMATS = ("wav", "aiff", "flac")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("index"))
        error = "Incorrect password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html", formats=SUPPORTED_FORMATS)


@app.route("/download", methods=["POST"])
@login_required
def start_download():
    url = request.form.get("url", "").strip()
    fmt = request.form.get("format", "flac")

    if not url:
        return jsonify({"error": "URL is required."}), 400
    if fmt not in SUPPORTED_FORMATS:
        return jsonify({"error": "Invalid format."}), 400
    if not (SOUNDCLOUD_RE.search(url) or SPOTIFY_RE.search(url)):
        return jsonify({"error": "URL must be from soundcloud.com or open.spotify.com."}), 400

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(DOWNLOADS_DIR, job_id)
    os.makedirs(job_dir)

    JOBS[job_id] = {"status": "running", "files": [], "error": None, "log": []}

    t = threading.Thread(target=_run_download, args=(job_id, url, fmt, job_dir), daemon=True)
    t.start()

    return jsonify({"job_id": job_id})


def _run_download(job_id, url, fmt, job_dir):
    try:
        if SOUNDCLOUD_RE.search(url):
            cmd = [
                "yt-dlp",
                "--extract-audio",
                "--audio-format", fmt,
                "--audio-quality", "0",
                "--output", os.path.join(job_dir, "%(playlist_index)s - %(title)s.%(ext)s"),
                "--yes-playlist",
                "--no-overwrites",
                "--newline",
                "--no-colors",
                "--socket-timeout", "30",
                url,
            ]
        else:
            cmd = [
                "spotdl",
                "--format", fmt,
                "--output", os.path.join(job_dir, "{title}"),
                url,
            ]

        JOBS[job_id]["log"].append(f"Running: {' '.join(cmd)}")
        print(f"[{job_id}] Running: {cmd}", flush=True)

        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=env,
        )

        print(f"[{job_id}] Process started, PID {proc.pid}", flush=True)

        fd = proc.stdout.fileno()
        buf = b""
        last_output = time.time()
        NO_OUTPUT_TIMEOUT = 120  # kill if silent for 2 minutes

        while True:
            # check if process already exited with no more data
            if proc.poll() is not None:
                try:
                    remaining = os.read(fd, 65536)
                    if remaining:
                        buf += remaining
                except OSError:
                    pass
                break

            # check for no-output timeout
            if time.time() - last_output > NO_OUTPUT_TIMEOUT:
                proc.kill()
                JOBS[job_id]["log"].append(
                    f"Killed: no output for {NO_OUTPUT_TIMEOUT}s — "
                    "SoundCloud may be blocking this server, or the URL is invalid."
                )
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = "Download timed out — no output from yt-dlp."
                return

            import select
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not ready:
                continue

            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break

            last_output = time.time()
            buf += chunk
            parts = re.split(rb"[\r\n]+", buf)
            for part in parts[:-1]:
                line = part.decode("utf-8", errors="replace").strip()
                if line:
                    JOBS[job_id]["log"].append(line)
                    print(f"[{job_id}] {line}", flush=True)
            buf = parts[-1]

        if buf:
            line = buf.decode("utf-8", errors="replace").strip()
            if line:
                JOBS[job_id]["log"].append(line)

        proc.wait()

        if proc.returncode != 0:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = "Download failed — check the log for details."
            return

        audio_exts = {".wav", ".aiff", ".flac", ".mp3", ".ogg"}
        files = sorted(
            f for f in os.listdir(job_dir)
            if os.path.splitext(f)[1].lower() in audio_exts
        )
        JOBS[job_id]["files"] = files
        JOBS[job_id]["status"] = "done"

        # auto-delete files after 2 hours
        def cleanup():
            time.sleep(7200)
            shutil.rmtree(job_dir, ignore_errors=True)
            JOBS.pop(job_id, None)

        threading.Thread(target=cleanup, daemon=True).start()

    except Exception as exc:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(exc)


@app.route("/status/<job_id>")
@login_required
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


@app.route("/files/<job_id>/<filename>")
@login_required
def download_file(job_id, filename):
    job_dir = os.path.abspath(os.path.join(DOWNLOADS_DIR, job_id))
    filepath = os.path.abspath(os.path.join(job_dir, filename))

    # prevent path traversal
    if not filepath.startswith(job_dir + os.sep):
        return "Forbidden", 403
    if not os.path.isfile(filepath):
        return "File not found", 404

    return send_file(filepath, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
