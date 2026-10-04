@echo off
cd /d "%~dp0"
start http://localhost:8000/web/
python -m http.server