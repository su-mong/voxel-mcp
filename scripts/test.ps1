$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    & $venvPython -m ruff check src tests examples
    if ($LASTEXITCODE -ne 0) { throw "Lint failed." }
    & $venvPython -m ruff format --check src tests examples
    if ($LASTEXITCODE -ne 0) { throw "Formatting check failed." }
    $tempParent = Join-Path $projectRoot "workspace\test-tmp"
    New-Item -ItemType Directory -Path $tempParent -Force | Out-Null
    $tempRoot = Join-Path $tempParent ([Guid]::NewGuid().ToString("N"))
    & $venvPython -m pytest -q "--basetemp=$tempRoot" --cov=voxel_mcp --cov-report=term-missing --cov-fail-under=85
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
} finally {
    Pop-Location
}

