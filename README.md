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

## Notes

- Spotify has no public audio downloads; `spotdl` matches each track via
  YouTube Music. Video mode is disabled for Spotify links.
- Archives use `.7z` (7-Zip). `.rar` is not supported because creating RAR
  archives requires proprietary WinRAR tooling.
- Only download content you have the rights to save.
