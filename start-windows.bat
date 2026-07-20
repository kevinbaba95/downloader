@echo off
REM One-click starter for Windows.
REM First run installs dependencies; needs Python 3.10+ from python.org
REM (check "Add python.exe to PATH" during install) and ffmpeg
REM (winget install ffmpeg).

cd /d "%~dp0"
py -m pip install -r requirements.txt --quiet || python -m pip install -r requirements.txt --quiet
start "" http://127.0.0.1:5000
py app.py || python app.py
pause
