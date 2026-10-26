param([string]$ServerName = "magicavoxel", [switch]$EnableLauncher)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) { throw "Run scripts/setup.ps1 first." }
$workspacePath = Join-Path $projectRoot "workspace"
$arguments = @("mcp", "add", $ServerName, "--env", "VOXEL_WORKSPACE=$workspacePath")
if ($EnableLauncher) {
    $executable = Join-Path $projectRoot "MagicaVoxel\MagicaVoxel.exe"
    if (-not (Test-Path -LiteralPath $executable)) { throw "Local MagicaVoxel.exe not found." }
    $arguments += @("--env", "MAGICAVOXEL_EXE=$executable")
}
$arguments += @("--", $venvPython, "-m", "voxel_mcp.server")
& codex @arguments
if ($LASTEXITCODE -ne 0) { throw "Codex MCP registration failed." }
Write-Host "Registered $ServerName. Restart the Codex MCP connection to load its tools."

