param(
  [string]$PluginPath = (Resolve-Path "$PSScriptRoot\..\..\openclaw-plugin").Path,
  [switch]$Link = $true,
  [switch]$InstallGatewayLoginItem
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-RandomHex([int]$ByteCount = 32) {
  $bytes = New-Object byte[] $ByteCount
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  return -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

$openclaw = Get-Command openclaw -ErrorAction SilentlyContinue
if (-not $openclaw) {
  throw "openclaw CLI not found on PATH."
}

$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) {
  throw "npm not found on PATH."
}

$hooksToken = [Environment]::GetEnvironmentVariable("OPENCLAW_HOOKS_TOKEN", "User")
if (-not $hooksToken) {
  $hooksToken = New-RandomHex
  [Environment]::SetEnvironmentVariable("OPENCLAW_HOOKS_TOKEN", $hooksToken, "User")
  Write-Host "Created user environment variable OPENCLAW_HOOKS_TOKEN."
}

$hooksConfig = @{
  enabled = $true
  token = $hooksToken
  path = "/hooks"
  maxBodyBytes = 262144
  defaultSessionKey = "hook:harness"
  allowRequestSessionKey = $true
  allowedSessionKeyPrefixes = @("hook:")
  allowedAgentIds = @("hooks", "main")
}

Write-Host "Installing plugin runtime dependencies in $PluginPath"
Push-Location $PluginPath
try {
  & $npm.Source install --omit=dev
  if ($LASTEXITCODE -ne 0) {
    throw "npm install failed for $PluginPath"
  }
} finally {
  Pop-Location
}

& $openclaw.Source config set gateway.mode local
if ($LASTEXITCODE -ne 0) {
  throw "Failed to set gateway.mode=local."
}

& $openclaw.Source config set gateway.bind loopback
if ($LASTEXITCODE -ne 0) {
  throw "Failed to set gateway.bind=loopback."
}

$configPath = Join-Path $env:USERPROFILE ".openclaw\openclaw.json"
if (-not (Test-Path $configPath)) {
  throw "OpenClaw config file not found at $configPath"
}

$config = Get-Content -Raw $configPath | ConvertFrom-Json
if ($config.PSObject.Properties.Name -notcontains "hooks") {
  $config | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]$hooksConfig)
} else {
  $config.hooks = [pscustomobject]$hooksConfig
}
$config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $configPath -Encoding UTF8

& $openclaw.Source config validate
if ($LASTEXITCODE -ne 0) {
  throw "Failed to validate updated hooks configuration."
}

try {
  & $openclaw.Source plugins uninstall clawharness --force | Out-Null
} catch {
}

# Remove the legacy plugin id if it was installed before the ClawHarness rename.
try {
  & $openclaw.Source plugins uninstall openclaw-harness --force | Out-Null
} catch {
}

$installArgs = @("plugins", "install", $PluginPath)
if ($Link.IsPresent) {
  $installArgs += "--link"
}

Write-Host "Installing ClawHarness plugin from $PluginPath"
& $openclaw.Source @installArgs
if ($LASTEXITCODE -ne 0) {
  throw "openclaw plugin install failed."
}

& $openclaw.Source plugins doctor
if ($LASTEXITCODE -ne 0) {
  throw "openclaw plugins doctor failed."
}

if ($InstallGatewayLoginItem.IsPresent) {
  & $openclaw.Source gateway install --force
  if ($LASTEXITCODE -ne 0) {
    throw "openclaw gateway install failed."
  }

  & $openclaw.Source gateway start
  if ($LASTEXITCODE -ne 0) {
    throw "openclaw gateway start failed."
  }

  Write-Host "OpenClaw gateway login item is installed and running."
} else {
  Write-Host "Gateway login item was skipped to avoid Startup-folder persistence."
  Write-Host "Start manually with: powershell -ExecutionPolicy Bypass -File deploy\\windows\\run-gateway.ps1"
}

Write-Host "OpenClaw hooks and ClawHarness plugin are configured."
