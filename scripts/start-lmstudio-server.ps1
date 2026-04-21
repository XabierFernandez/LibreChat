param(
  [int]$Port = 1235
)

$ErrorActionPreference = "Stop"

function Test-LmStudioEndpoint {
  param([int]$TargetPort)

  try {
    $null = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$TargetPort/v1/models" -TimeoutSec 5
    return $true
  } catch {
    return $false
  }
}

$lmstudioExe = "C:\Users\xabie\.lmstudio\bin\lms.exe"
$permissionsFile = "C:\Users\xabie\.lmstudio\.internal\permissions-store.json"

if (-not (Test-Path $lmstudioExe)) {
  throw "LM Studio CLI not found at $lmstudioExe"
}

if (Test-Path $permissionsFile) {
  try {
    $raw = Get-Content -Raw -Path $permissionsFile | ConvertFrom-Json
    if ($raw.tokenMode -ne "none") {
      $raw.tokenMode = "none"
      $raw | ConvertTo-Json -Depth 16 | Set-Content -Path $permissionsFile -Encoding UTF8
    }
  } catch {
    Write-Warning "Could not update LM Studio permissions-store.json: $($_.Exception.Message)"
  }
}

if (Test-LmStudioEndpoint -TargetPort $Port) {
  Write-Host "LM Studio server already ready on port $Port"
  exit 0
}

Start-Process -FilePath $lmstudioExe -ArgumentList @("server", "start", "--port", "$Port", "--bind", "0.0.0.0") -WindowStyle Hidden

for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  if (Test-LmStudioEndpoint -TargetPort $Port) {
    Write-Host "LM Studio server ready on port $Port"
    exit 0
  }
}

throw "LM Studio server did not become ready on port $Port"
