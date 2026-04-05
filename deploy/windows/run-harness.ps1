param(
  [string]$PythonExe = "python",
  [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Set-ProcessEnvFromUser([string]$Name) {
  $value = [Environment]::GetEnvironmentVariable($Name, "User")
  if ($value) {
    Set-Item -Path ("Env:" + $Name) -Value $value
  }
  return $value
}

$python = Get-Command $PythonExe -ErrorAction SilentlyContinue
if (-not $python) {
  throw "python not found on PATH."
}

$hooksToken = Set-ProcessEnvFromUser "OPENCLAW_HOOKS_TOKEN"
if (-not $hooksToken) {
  throw "OPENCLAW_HOOKS_TOKEN is missing. Run deploy/windows/install-openclaw.ps1 first."
}

$ingressToken = Set-ProcessEnvFromUser "HARNESS_INGRESS_TOKEN"
if (-not $ingressToken) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  $ingressToken = -join ($bytes | ForEach-Object { $_.ToString("x2") })
  [Environment]::SetEnvironmentVariable("HARNESS_INGRESS_TOKEN", $ingressToken, "User")
  Set-Item -Path Env:HARNESS_INGRESS_TOKEN -Value $ingressToken
  Write-Host "Created user environment variable HARNESS_INGRESS_TOKEN."
}

$null = Set-ProcessEnvFromUser "ADO_BASE_URL"
$null = Set-ProcessEnvFromUser "ADO_PROJECT"
$null = Set-ProcessEnvFromUser "ADO_PAT"
$null = Set-ProcessEnvFromUser "ADO_WEBHOOK_SECRET"
$null = Set-ProcessEnvFromUser "RC_WEBHOOK_URL"
$env:PYTHONUNBUFFERED = "1"

Push-Location $RepoRoot
try {
  & $python.Source -m harness_runtime.main --bind 127.0.0.1 --port 8080
} finally {
  Pop-Location
}
