# Downloader

Web app + CLI for downloading tracks, playlists, and videos from
**SoundCloud**, **Spotify**, and **YouTube**.

## Features

- Lossless audio output: **FLAC** or **WAV**
- **Video downloads** (YouTube/SoundCloud) with a min–max resolution range
- Playlists are compressed into a single **.7z** archive
- Live **progress bar** with per-track status
- **Rate-limit resilience**: exponential-backoff retries and request pacing
  so downloads survive HTTP 429/4xx hiccups
- Clear, human-readable error messages when a file can't be downloaded
  (private, region-locked, deleted, rate-limited…)
- One-click **Clear** button that resets the link and the output

## Setup

```bash
pip install -r requirements.txt
# ffmpeg is required for audio conversion:
sudo apt install ffmpeg   # Linux
brew install ffmpeg       # macOS
```

## Run the web app

```bash
python app.py
# open http://127.0.0.1:5000
```

Paste a link, pick Audio (FLAC/WAV) or Video (resolution range), and hit
**Download**. When the job finishes, a **Save file** button appears —
single tracks download directly, playlists as `playlist.7z`.

## CLI

```bash
python downloader.py <URL> -f flac -o downloads
```

## SoundCloud says everything is "DRM protected"?

SoundCloud currently reports false DRM errors for anonymous clients
(see yt-dlp issues #16755/#16603). Fix:

1. Keep yt-dlp current: `pip install -U yt-dlp`
2. Log into soundcloud.com in your browser, export cookies with a
   "cookies.txt" extension (e.g. *Get cookies.txt LOCALLY*), and save the
   file as `cookies.txt` next to `app.py`
3. Restart the app — it picks the file up automatically
   (or set `YTDLP_COOKIES=/path/to/cookies.txt`)

Genuine DRM (major-label Go+ streams) still can't be downloaded.

## Notes

- Spotify has no public audio downloads; `spotdl` matches each track via
  YouTube Music. Video mode is disabled for Spotify links.
- Archives use `.7z` (7-Zip). `.rar` is not supported because creating RAR
  archives requires proprietary WinRAR tooling.
- Only download content you have the rights to save.
