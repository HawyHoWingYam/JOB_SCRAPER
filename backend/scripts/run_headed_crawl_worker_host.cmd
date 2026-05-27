@echo off
setlocal

set "REPO=%~dp0..\.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

set "PREPARE=%REPO%\backend\scripts\prepare_headed_crawl_worker_host.py"
set "PYTHON=%REPO%\backend\.host_worker_venv\Scripts\python.exe"
set "SCRIPT=%REPO%\backend\scripts\run_headed_crawl_worker.py"

if not defined JOBSDB_HEADED_BROWSER_CHANNEL set "JOBSDB_HEADED_BROWSER_CHANNEL=msedge"
set "PROFILE=%REPO%\backend\.host_browser_profiles\%JOBSDB_HEADED_BROWSER_CHANNEL%"

set "DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb"
set "REDIS_URL=redis://localhost:6379/0"
set "JOBSDB_HEADED_BROWSER_USER_DATA_DIR=%PROFILE%"

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
  echo Missing worker script: %SCRIPT%
  pause
  exit /b 1
)

if not exist "%PYTHON%" (
  echo Missing Python runtime after bootstrap: %PYTHON%
  pause
  exit /b 1
)

if not exist "%PROFILE%" (
  echo Missing browser profile directory after bootstrap: %PROFILE%
  pause
  exit /b 1
)

echo DATABASE_URL=%DATABASE_URL%
echo REDIS_URL=%REDIS_URL%
echo JOBSDB_HEADED_BROWSER_CHANNEL=%JOBSDB_HEADED_BROWSER_CHANNEL%
echo JOBSDB_HEADED_BROWSER_USER_DATA_DIR=%JOBSDB_HEADED_BROWSER_USER_DATA_DIR%

"%PYTHON%" "%SCRIPT%"
if errorlevel 1 (
  echo Headed crawl worker exited with error level %errorlevel%.
  pause
  exit /b %errorlevel%
)
