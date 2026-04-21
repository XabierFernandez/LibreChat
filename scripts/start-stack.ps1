$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot

& "$PSScriptRoot\start-lmstudio-server.ps1"

Push-Location $projectRoot
try {
  docker compose up -d --build
} finally {
  Pop-Location
}
