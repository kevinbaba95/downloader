#!/usr/bin/env bash
# One-click starter for macOS/Linux. Needs python3.10+ and ffmpeg
# (macOS: brew install ffmpeg / Linux: sudo apt install ffmpeg).
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt --quiet
( sleep 2; open http://127.0.0.1:5000 2>/dev/null || xdg-open http://127.0.0.1:5000 2>/dev/null ) &
python3 app.py
