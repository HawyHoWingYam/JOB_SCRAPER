$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$prepare = Join-Path $repo 'backend\scripts\prepare_headed_crawl_worker_host.py'
$python = Join-Path $repo 'backend\.host_worker_venv\Scripts\python.exe'
$script = Join-Path $repo 'backend\scripts\run_headed_crawl_worker.py'
$browserChannel = if ($env:JOBSDB_HEADED_BROWSER_CHANNEL) { $env:JOBSDB_HEADED_BROWSER_CHANNEL } else { 'msedge' }
$profile = Join-Path $repo ("backend\.host_browser_profiles\" + $browserChannel)

$env:DATABASE_URL = 'postgresql://admin:dev_password@localhost:5433/jobsdb'
$env:REDIS_URL = 'redis://localhost:6379/0'
$env:JOBSDB_HEADED_BROWSER_CHANNEL = $browserChannel
$env:JOBSDB_HEADED_BROWSER_USER_DATA_DIR = $profile

if (-not (Test-Path $python)) {
  Write-Output "Preparing host worker runtime..."
  & python $prepare
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare host worker runtime."
  }
}

Write-Output "DATABASE_URL=$env:DATABASE_URL"
Write-Output "REDIS_URL=$env:REDIS_URL"
Write-Output "JOBSDB_HEADED_BROWSER_CHANNEL=$env:JOBSDB_HEADED_BROWSER_CHANNEL"
Write-Output "JOBSDB_HEADED_BROWSER_USER_DATA_DIR=$env:JOBSDB_HEADED_BROWSER_USER_DATA_DIR"

& $python $script
