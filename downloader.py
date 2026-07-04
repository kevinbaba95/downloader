#!/usr/bin/env python3
"""
Music downloader for SoundCloud and Spotify.
SoundCloud: uses yt-dlp with ffmpeg post-processing.
Spotify: uses spotdl, which matches tracks via YouTube Music.
"""

import argparse
import subprocess
import sys
import re

SOUNDCLOUD_PATTERN = re.compile(r"soundcloud\.com", re.IGNORECASE)
SPOTIFY_PATTERN = re.compile(r"open\.spotify\.com", re.IGNORECASE)

SUPPORTED_FORMATS = ("wav", "flac")


def check_dependency(command: str) -> bool:
    try:
        subprocess.run([command, "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def download_soundcloud(url: str, fmt: str, output_dir: str) -> None:
    if not check_dependency("yt-dlp"):
        sys.exit("Error: yt-dlp is not installed. Run: pip install yt-dlp")
    if not check_dependency("ffmpeg"):
        sys.exit("Error: ffmpeg is not installed. Install it via your package manager.")

    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", fmt,
        "--audio-quality", "0",
        # Rate-limit resilience: retry with backoff, pace requests
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "http:exp=3:60",
        "--sleep-requests", "0.75",
        "--output", f"{output_dir}/%(uploader)s/%(playlist_title)s/%(playlist_index)s - %(title)s.%(ext)s",
        "--yes-playlist",
        "--no-overwrites",
        "--progress",
        url,
    ]

    print(f"Downloading from SoundCloud as {fmt.upper()} → {output_dir}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"yt-dlp exited with code {result.returncode}")


def download_spotify(url: str, fmt: str, output_dir: str) -> None:
    if not check_dependency("spotdl"):
        sys.exit("Error: spotdl is not installed. Run: pip install spotdl")

    cmd = [
        "spotdl",
        "--format", fmt,
        "--output", f"{output_dir}/{{artist}}/{{album}}/{{track-number}} - {{title}}",
        "--max-retries", "8",
        url,
    ]

    print(f"Downloading from Spotify as {fmt.upper()} → {output_dir}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"spotdl exited with code {result.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download SoundCloud or Spotify tracks and playlists.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://soundcloud.com/artist/sets/playlist -f flac
  %(prog)s https://open.spotify.com/playlist/... -f wav -o ~/Music
  %(prog)s https://soundcloud.com/artist/track -f aiff
        """,
    )
    parser.add_argument("url", help="SoundCloud or Spotify URL (track or playlist)")
    parser.add_argument(
        "-f", "--format",
        choices=SUPPORTED_FORMATS,
        default="flac",
        help="Output audio format (default: flac)",
    )
    parser.add_argument(
        "-o", "--output",
        default="downloads",
        help="Output directory (default: ./downloads)",
    )

    args = parser.parse_args()

    if SOUNDCLOUD_PATTERN.search(args.url):
        download_soundcloud(args.url, args.format, args.output)
    elif SPOTIFY_PATTERN.search(args.url):
        download_spotify(args.url, args.format, args.output)
    else:
        sys.exit("Error: URL must be from soundcloud.com or open.spotify.com")


if __name__ == "__main__":
    main()
