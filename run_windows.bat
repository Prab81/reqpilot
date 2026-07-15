@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install it and run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: creating the ReqPilot Python environment...
  python -m venv .venv || exit /b 1
  .venv\Scripts\python -m pip install --upgrade pip || exit /b 1
  .venv\Scripts\python -m pip install -r requirements.txt || exit /b 1
)

echo Checking local speech models...
.venv\Scripts\python -m scripts.fetch_models || (
  pause
  exit /b 1
)

echo Starting ReqPilot at http://127.0.0.1:8765
.venv\Scripts\python -m src.server
endlocal
