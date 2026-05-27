$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$prepare = Join-Path $repo 'backend\scripts\prepare_headed_crawl_worker_host.py'
$python = Join-Path $repo 'backend\.host_worker_venv\Scripts\python.exe'
$script = Join-Path $repo 'backend\scripts\run_manual_action_helper.py'

$env:DATABASE_URL = 'postgresql://admin:dev_password@localhost:5433/jobsdb'

if (-not (Test-Path $python)) {
  Write-Output "Preparing host worker runtime..."
  & python $prepare
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare host worker runtime."
  }
}

Write-Output "DATABASE_URL=$env:DATABASE_URL"

& $python $script
