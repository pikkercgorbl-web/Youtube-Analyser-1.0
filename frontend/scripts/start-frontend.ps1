# Launch frontend from frontend/ (delegates to repo scripts/start-frontend.ps1).
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
& (Join-Path $RepoRoot "scripts\start-frontend.ps1")
