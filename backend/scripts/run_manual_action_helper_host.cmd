@echo off
setlocal

set "REPO=%~dp0..\.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

set "PREPARE=%REPO%\backend\scripts\prepare_headed_crawl_worker_host.py"
set "PYTHON=%REPO%\backend\.host_worker_venv\Scripts\python.exe"
set "SCRIPT=%REPO%\backend\scripts\run_manual_action_helper.py"

set "DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb"

if not exist "%PREPARE%" (
  echo Missing bootstrap script: %PREPARE%
  pause
  exit /b 1
)

set "BOOTSTRAP_PYTHON="
python -c "import sys" >nul 2>nul && set "BOOTSTRAP_PYTHON=python"
if not defined BOOTSTRAP_PYTHON (
  py -3.11 -c "import sys" >nul 2>nul && set "BOOTSTRAP_PYTHON=py -3.11"
)
if not defined BOOTSTRAP_PYTHON (
  py -3 -c "import sys" >nul 2>nul && set "BOOTSTRAP_PYTHON=py -3"
)
if not defined BOOTSTRAP_PYTHON (
  py -c "import sys" >nul 2>nul && set "BOOTSTRAP_PYTHON=py"
)

if not defined BOOTSTRAP_PYTHON (
  echo Missing system Python launcher. Install Python 3.11 and ensure `python` or `py` is available.
  pause
  exit /b 1
)

if not exist "%PYTHON%" (
  echo Preparing host worker runtime with %BOOTSTRAP_PYTHON%...
  call %BOOTSTRAP_PYTHON% "%PREPARE%"
  if errorlevel 1 (
    echo Failed to prepare host worker runtime.
    pause
    exit /b %errorlevel%
  )
)

if not exist "%SCRIPT%" (
  echo Missing helper script: %SCRIPT%
  pause
  exit /b 1
)

if not exist "%PYTHON%" (
  echo Missing Python runtime after bootstrap: %PYTHON%
  pause
  exit /b 1
)

echo DATABASE_URL=%DATABASE_URL%

"%PYTHON%" "%SCRIPT%"
if errorlevel 1 (
  echo Manual action helper exited with error level %errorlevel%.
  pause
  exit /b %errorlevel%
)
