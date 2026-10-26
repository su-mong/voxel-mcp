param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & $Python -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'"
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required. Pass -Python with the full python.exe path." }
    & $Python -m venv .venv
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if ($LASTEXITCODE -ne 0) {
        # Bundled Codex runtimes may provide pip but not ensurepip.
        & $Python -m venv --without-pip .venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create .venv." }
        & $Python -m pip --python $venvPython install -r requirements.lock
    } else {
        & $venvPython -m pip install -r requirements.lock
    }
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & $venvPython -m pip install --no-build-isolation --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw "Package installation failed." }
    Write-Host "Ready: $venvPython -m voxel_mcp.server"
} finally {
    Pop-Location
}

