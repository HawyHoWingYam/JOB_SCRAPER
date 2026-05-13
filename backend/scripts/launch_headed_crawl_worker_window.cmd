@echo off
setlocal

set "REPO=%~dp0..\.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

set "RUNNER=%REPO%\backend\scripts\run_headed_crawl_worker_host.cmd"

if not exist "%RUNNER%" (
  echo Missing runner script: %RUNNER%
  pause
  exit /b 1
)

start "JobsDB Headed Crawl Worker" cmd /k "%RUNNER%"
