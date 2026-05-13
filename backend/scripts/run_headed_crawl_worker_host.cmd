@echo off
setlocal

set "REPO=%~dp0..\.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

set "PYTHON=%REPO%\backend\.host_worker_venv\Scripts\python.exe"
set "SCRIPT=%REPO%\backend\scripts\run_headed_crawl_worker.py"
set "PROFILE=%REPO%\backend\.host_browser_profiles\msedge"

set "DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb"
set "REDIS_URL=redis://localhost:6379/0"
set "JOBSDB_HEADED_BROWSER_CHANNEL=msedge"
set "JOBSDB_HEADED_BROWSER_USER_DATA_DIR=%PROFILE%"

if not exist "%PYTHON%" (
  echo Missing Python runtime: %PYTHON%
  pause
  exit /b 1
)

if not exist "%SCRIPT%" (
  echo Missing worker script: %SCRIPT%
  pause
  exit /b 1
)

if not exist "%PROFILE%" (
  echo Missing browser profile directory: %PROFILE%
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
