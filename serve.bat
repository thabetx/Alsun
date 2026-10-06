@echo off
cd /d "%~dp0"
echo Starting Alsun... the browser opens by itself when the server is ready.
rem The browser used to open first, before the server was listening, and showed an error for the seconds the
rem server needed to start. Now a second process waits for /health to answer and opens the page then.
start "" /b powershell -NoProfile -Command "for ($i = 0; $i -lt 240; $i++) { try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2 | Out-Null; Start-Process http://127.0.0.1:8000/; break } catch { Start-Sleep -Milliseconds 500 } }"
.venv\Scripts\python -m uvicorn python.main:app --host 127.0.0.1 --port 8000
