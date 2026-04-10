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

function Resolve-ProvidersConfigPath([string]$Root) {
  $profile = (Set-ProcessEnvFromUser "HARNESS_PROVIDER_PROFILE")
  if (-not $profile) {
    $profile = "local-task"
    Set-Item -Path Env:HARNESS_PROVIDER_PROFILE -Value $profile
  }

  switch ($profile.ToLowerInvariant()) {
    "azure-devops" { $path = Join-Path $Root "deploy\config\providers.azure-devops.yaml" }
    "github" { $path = Join-Path $Root "deploy\config\providers.github.yaml" }
    default { $path = Join-Path $Root "deploy\config\providers.yaml" }
  }

  if (-not (Test-Path $path)) {
    throw "Providers config not found for HARNESS_PROVIDER_PROFILE=$profile at $path"
  }

  return $path
}

$python = Get-Command $PythonExe -ErrorAction SilentlyContinue
if (-not $python) {
  throw "python not found on PATH."
}

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
  throw "git not found on PATH."
}

$codex = Get-Command codex -ErrorAction SilentlyContinue
if (-not $codex) {
  throw "codex CLI not found on PATH."
}

$ingressToken = Set-ProcessEnvFromUser "HARNESS_INGRESS_TOKEN"
if (-not $ingressToken) {
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $rng.GetBytes($bytes)
  } finally {
    $rng.Dispose()
  }
  $ingressToken = -join ($bytes | ForEach-Object { $_.ToString("x2") })
  [Environment]::SetEnvironmentVariable("HARNESS_INGRESS_TOKEN", $ingressToken, "User")
  Set-Item -Path Env:HARNESS_INGRESS_TOKEN -Value $ingressToken
  Write-Host "Created user environment variable HARNESS_INGRESS_TOKEN."
}

$null = Set-ProcessEnvFromUser "OPENAI_API_KEY"
$null = Set-ProcessEnvFromUser "OPENAI_BASE_URL"
$null = Set-ProcessEnvFromUser "CODEX_MODEL"
$null = Set-ProcessEnvFromUser "CODEX_REVIEW_MODEL"
$null = Set-ProcessEnvFromUser "CODEX_REASONING_EFFORT"
$null = Set-ProcessEnvFromUser "HARNESS_IMAGE_MODEL"
$executorBackend = Set-ProcessEnvFromUser "HARNESS_EXECUTOR_BACKEND"
if (-not $executorBackend) {
  $env:HARNESS_EXECUTOR_BACKEND = "codex-cli"
}
$null = Set-ProcessEnvFromUser "ADO_BASE_URL"
$null = Set-ProcessEnvFromUser "ADO_PROJECT"
$null = Set-ProcessEnvFromUser "ADO_PAT"
$null = Set-ProcessEnvFromUser "ADO_WEBHOOK_SECRET"
$null = Set-ProcessEnvFromUser "GITHUB_TOKEN"
$null = Set-ProcessEnvFromUser "GITHUB_WEBHOOK_SECRET"
$null = Set-ProcessEnvFromUser "RC_WEBHOOK_URL"
$null = Set-ProcessEnvFromUser "RC_COMMAND_TOKEN"
$null = Set-ProcessEnvFromUser "LOCAL_REPO_PATH"
$null = Set-ProcessEnvFromUser "LOCAL_TASKS_PATH"
$null = Set-ProcessEnvFromUser "LOCAL_REVIEW_PATH"
$null = Set-ProcessEnvFromUser "LOCAL_BASE_BRANCH"
$null = Set-ProcessEnvFromUser "LOCAL_PUSH_ENABLED"
$null = Set-ProcessEnvFromUser "HARNESS_READONLY_TOKEN"
$null = Set-ProcessEnvFromUser "HARNESS_CONTROL_TOKEN"
$providersConfig = Resolve-ProvidersConfigPath -Root $RepoRoot
$policyConfig = Join-Path $RepoRoot "deploy\config\harness-policy.yaml"
$openclawConfig = Join-Path $RepoRoot "deploy\config\openclaw.json"
$env:HARNESS_SHELL_ENABLED = "0"
$env:PYTHONUNBUFFERED = "1"

Push-Location $RepoRoot
try {
  & $python.Source -m harness_runtime.main `
    --providers-config $providersConfig `
    --policy-config $policyConfig `
    --openclaw-config $openclawConfig `
    --bind 127.0.0.1 `
    --port 8080
} finally {
  Pop-Location
}
