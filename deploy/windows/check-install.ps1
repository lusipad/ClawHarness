param(
  [ValidateSet("docker", "native-core", "native-openclaw")]
  [string]$InstallMode = "docker",
  [ValidateSet("core", "shell", "bot-view")]
  [string]$Profile = "core",
  [ValidateSet("local-task", "azure-devops", "github")]
  [string]$ProviderProfile = "local-task",
  [switch]$CheckRuntime
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-CheckLayout {
  $bundleCompose = Join-Path $PSScriptRoot "compose.yml"
  $bundleEnvExample = Join-Path $PSScriptRoot ".env.example"
  if ((Test-Path $bundleCompose) -and (Test-Path $bundleEnvExample)) {
    $projectRoot = (Resolve-Path $PSScriptRoot).Path
    return [pscustomobject]@{
      Mode = "bundle"
      ProjectRoot = $projectRoot
      NativeRoot = Join-Path $projectRoot "src"
      EnvFile = Join-Path $projectRoot ".env"
      ComposeFile = (Resolve-Path $bundleCompose).Path
    }
  }

  $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
  $repoCompose = Join-Path $repoRoot "deploy\docker\compose.yml"
  if (Test-Path $repoCompose) {
    return [pscustomobject]@{
      Mode = "repo"
      ProjectRoot = $repoRoot
      NativeRoot = $repoRoot
      EnvFile = Join-Path $repoRoot "deploy\docker\.env"
      ComposeFile = $repoCompose
    }
  }

  throw "Could not resolve installation layout from $PSScriptRoot"
}

function Add-CheckResult(
  [System.Collections.Generic.List[object]]$Results,
  [string]$Name,
  [bool]$Ok,
  [string]$Detail
) {
  $Results.Add([pscustomobject]@{
      name = $Name
      ok = $Ok
      detail = $Detail
    }) | Out-Null
}

function Write-CheckResults([System.Collections.Generic.List[object]]$Results) {
  foreach ($result in $Results) {
    $prefix = if ($result.ok) { "[OK]" } else { "[MISSING]" }
    Write-Host "$prefix $($result.name): $($result.detail)"
  }
}

function Get-UserOrProcessEnvValue([string]$Name) {
  $processValue = [Environment]::GetEnvironmentVariable($Name, "Process")
  if ($processValue) {
    return $processValue
  }
  return [Environment]::GetEnvironmentVariable($Name, "User")
}

function Get-DotEnvMap([string]$Path) {
  $values = @{}
  if (-not (Test-Path $Path)) {
    return $values
  }

  foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
    if ($line -match '^\s*#' -or $line -match '^\s*$') {
      continue
    }
    if ($line -match '^\s*([^=]+)=(.*)$') {
      $values[$Matches[1].Trim()] = $Matches[2]
    }
  }
  return $values
}

function Resolve-ProviderProfile(
  [string]$InstallModeValue,
  [string]$RequestedProfile,
  [hashtable]$DotEnv
) {
  if ($InstallModeValue -eq "docker") {
    $value = $DotEnv["HARNESS_PROVIDER_PROFILE"]
    if ($value) {
      return $value
    }
    return $RequestedProfile
  }

  $userValue = Get-UserOrProcessEnvValue "HARNESS_PROVIDER_PROFILE"
  if ($userValue) {
    return $userValue
  }
  return $RequestedProfile
}

function Test-CommandAvailable([string]$Name) {
  return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-HttpOk([string]$Uri) {
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 10
    return ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 400)
  } catch {
    return $false
  }
}

function Resolve-PathValue([string]$ProjectRoot, [string]$RawValue) {
  if (-not $RawValue) {
    return $null
  }

  if ([System.IO.Path]::IsPathRooted($RawValue)) {
    return [System.IO.Path]::GetFullPath($RawValue)
  }

  return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $RawValue))
}

$layout = Resolve-CheckLayout
$results = New-Object 'System.Collections.Generic.List[object]'
$dotEnv = Get-DotEnvMap -Path $layout.EnvFile
$effectiveProviderProfile = Resolve-ProviderProfile -InstallModeValue $InstallMode -RequestedProfile $ProviderProfile -DotEnv $dotEnv

Add-CheckResult -Results $results -Name "layout" -Ok $true -Detail "$($layout.Mode) at $($layout.ProjectRoot)"

switch ($InstallMode) {
  "docker" {
    Add-CheckResult -Results $results -Name ".env" -Ok (Test-Path $layout.EnvFile) -Detail $layout.EnvFile
    Add-CheckResult -Results $results -Name "docker" -Ok (Test-CommandAvailable "docker") -Detail "docker command"
    $composeAvailable = $false
    if (Test-CommandAvailable "docker") {
      & docker compose version *> $null
      $composeAvailable = ($LASTEXITCODE -eq 0)
    }
    Add-CheckResult -Results $results -Name "docker compose" -Ok $composeAvailable -Detail "docker compose subcommand"

    $openAiApiKey = $dotEnv["OPENAI_API_KEY"]
    Add-CheckResult -Results $results -Name "OPENAI_API_KEY" -Ok ([bool]$openAiApiKey) -Detail "from .env"
    Add-CheckResult -Results $results -Name "HARNESS_PROVIDER_PROFILE" -Ok ([bool]$effectiveProviderProfile) -Detail $effectiveProviderProfile

    switch ($effectiveProviderProfile) {
      "local-task" {
        foreach ($entry in @(
          @{ Name = "LOCAL_REPO_DIR"; Value = $dotEnv["LOCAL_REPO_DIR"] },
          @{ Name = "LOCAL_TASKS_DIR"; Value = $dotEnv["LOCAL_TASKS_DIR"] },
          @{ Name = "LOCAL_REVIEW_DIR"; Value = $dotEnv["LOCAL_REVIEW_DIR"] }
        )) {
          $resolved = Resolve-PathValue -ProjectRoot $layout.ProjectRoot -RawValue $entry.Value
          $detail = if ($resolved) { $resolved } else { "not configured" }
          Add-CheckResult -Results $results -Name $entry.Name -Ok ([bool]$resolved -and (Test-Path $resolved)) -Detail $detail
        }
      }
      "azure-devops" {
        foreach ($name in "ADO_BASE_URL", "ADO_PROJECT", "ADO_PAT") {
          Add-CheckResult -Results $results -Name $name -Ok ([bool]$dotEnv[$name]) -Detail "from .env"
        }
      }
      "github" {
        Add-CheckResult -Results $results -Name "GITHUB_TOKEN" -Ok ([bool]$dotEnv["GITHUB_TOKEN"]) -Detail "from .env"
      }
    }

    if ($Profile -eq "shell" -or $Profile -eq "bot-view") {
      Add-CheckResult -Results $results -Name "OPENCLAW_GATEWAY_TOKEN" -Ok ([bool]$dotEnv["OPENCLAW_GATEWAY_TOKEN"]) -Detail "from .env"
      Add-CheckResult -Results $results -Name "OPENCLAW_HOOKS_TOKEN" -Ok ([bool]$dotEnv["OPENCLAW_HOOKS_TOKEN"]) -Detail "from .env"
    }
    if ($Profile -eq "bot-view") {
      $hasBotViewToken = [bool]($dotEnv["HARNESS_CONTROL_TOKEN"] -or $dotEnv["HARNESS_API_TOKEN"] -or $dotEnv["HARNESS_READONLY_TOKEN"])
      Add-CheckResult -Results $results -Name "bot-view token" -Ok $hasBotViewToken -Detail "HARNESS_CONTROL_TOKEN or HARNESS_API_TOKEN or HARNESS_READONLY_TOKEN"
    }

    if ($CheckRuntime.IsPresent) {
      Add-CheckResult -Results $results -Name "bridge health" -Ok (Test-HttpOk "http://127.0.0.1:8080/healthz") -Detail "http://127.0.0.1:8080/healthz"
      if ($Profile -eq "shell" -or $Profile -eq "bot-view") {
        Add-CheckResult -Results $results -Name "gateway health" -Ok (Test-HttpOk "http://127.0.0.1:18789/healthz") -Detail "http://127.0.0.1:18789/healthz"
      }
      if ($Profile -eq "bot-view") {
        Add-CheckResult -Results $results -Name "bot-view" -Ok (Test-HttpOk "http://127.0.0.1:3001") -Detail "http://127.0.0.1:3001"
      }
    }
  }
  "native-core" {
    foreach ($entry in @(
      @{ Name = "python"; Ok = (Test-CommandAvailable "python"); Detail = "python command" },
      @{ Name = "git"; Ok = (Test-CommandAvailable "git"); Detail = "git command" },
      @{ Name = "codex"; Ok = (Test-CommandAvailable "codex"); Detail = "codex command" },
      @{ Name = "run-harness-core.ps1"; Ok = (Test-Path (Join-Path $layout.NativeRoot "deploy\windows\run-harness-core.ps1")); Detail = "native core launcher" }
    )) {
      Add-CheckResult -Results $results -Name $entry.Name -Ok $entry.Ok -Detail $entry.Detail
    }

    foreach ($name in "OPENAI_API_KEY", "HARNESS_PROVIDER_PROFILE", "HARNESS_EXECUTOR_BACKEND", "HARNESS_INGRESS_TOKEN") {
      $value = Get-UserOrProcessEnvValue $name
      Add-CheckResult -Results $results -Name $name -Ok ([bool]$value) -Detail "user/process environment"
    }

    switch ($effectiveProviderProfile) {
      "local-task" {
        foreach ($name in "LOCAL_REPO_PATH", "LOCAL_TASKS_PATH", "LOCAL_REVIEW_PATH") {
          $value = Get-UserOrProcessEnvValue $name
          $detail = if ($value) { $value } else { "not configured" }
          Add-CheckResult -Results $results -Name $name -Ok ([bool]$value -and (Test-Path $value)) -Detail $detail
        }
      }
      "azure-devops" {
        foreach ($name in "ADO_BASE_URL", "ADO_PROJECT", "ADO_PAT") {
          $value = Get-UserOrProcessEnvValue $name
          Add-CheckResult -Results $results -Name $name -Ok ([bool]$value) -Detail "user/process environment"
        }
      }
      "github" {
        $value = Get-UserOrProcessEnvValue "GITHUB_TOKEN"
        Add-CheckResult -Results $results -Name "GITHUB_TOKEN" -Ok ([bool]$value) -Detail "user/process environment"
      }
    }

    if ($CheckRuntime.IsPresent) {
      Add-CheckResult -Results $results -Name "bridge health" -Ok (Test-HttpOk "http://127.0.0.1:8080/healthz") -Detail "http://127.0.0.1:8080/healthz"
    }
  }
  "native-openclaw" {
    foreach ($entry in @(
      @{ Name = "python"; Ok = (Test-CommandAvailable "python"); Detail = "python command" },
      @{ Name = "git"; Ok = (Test-CommandAvailable "git"); Detail = "git command" },
      @{ Name = "codex"; Ok = (Test-CommandAvailable "codex"); Detail = "codex command" },
      @{ Name = "node"; Ok = (Test-CommandAvailable "node"); Detail = "node command" },
      @{ Name = "npm"; Ok = (Test-CommandAvailable "npm"); Detail = "npm command" },
      @{ Name = "openclaw"; Ok = (Test-CommandAvailable "openclaw"); Detail = "openclaw command" },
      @{ Name = "run-gateway.ps1"; Ok = (Test-Path (Join-Path $layout.NativeRoot "deploy\windows\run-gateway.ps1")); Detail = "gateway launcher" },
      @{ Name = "run-harness.ps1"; Ok = (Test-Path (Join-Path $layout.NativeRoot "deploy\windows\run-harness.ps1")); Detail = "bridge launcher" }
    )) {
      Add-CheckResult -Results $results -Name $entry.Name -Ok $entry.Ok -Detail $entry.Detail
    }

    foreach ($name in "OPENAI_API_KEY", "HARNESS_PROVIDER_PROFILE", "HARNESS_EXECUTOR_BACKEND", "HARNESS_INGRESS_TOKEN", "OPENCLAW_GATEWAY_TOKEN", "OPENCLAW_HOOKS_TOKEN") {
      $value = Get-UserOrProcessEnvValue $name
      Add-CheckResult -Results $results -Name $name -Ok ([bool]$value) -Detail "user/process environment"
    }

    switch ($effectiveProviderProfile) {
      "local-task" {
        foreach ($name in "LOCAL_REPO_PATH", "LOCAL_TASKS_PATH", "LOCAL_REVIEW_PATH") {
          $value = Get-UserOrProcessEnvValue $name
          $detail = if ($value) { $value } else { "not configured" }
          Add-CheckResult -Results $results -Name $name -Ok ([bool]$value -and (Test-Path $value)) -Detail $detail
        }
      }
      "azure-devops" {
        foreach ($name in "ADO_BASE_URL", "ADO_PROJECT", "ADO_PAT") {
          $value = Get-UserOrProcessEnvValue $name
          Add-CheckResult -Results $results -Name $name -Ok ([bool]$value) -Detail "user/process environment"
        }
      }
      "github" {
        $value = Get-UserOrProcessEnvValue "GITHUB_TOKEN"
        Add-CheckResult -Results $results -Name "GITHUB_TOKEN" -Ok ([bool]$value) -Detail "user/process environment"
      }
    }

    if ($CheckRuntime.IsPresent) {
      Add-CheckResult -Results $results -Name "gateway health" -Ok (Test-HttpOk "http://127.0.0.1:18789/healthz") -Detail "http://127.0.0.1:18789/healthz"
      Add-CheckResult -Results $results -Name "bridge health" -Ok (Test-HttpOk "http://127.0.0.1:8080/healthz") -Detail "http://127.0.0.1:8080/healthz"
    }
  }
}

Write-CheckResults -Results $results

$failed = @($results | Where-Object { -not $_.ok })
if ($failed.Count -gt 0) {
  Write-Host "install_check_failed ($($failed.Count) issue(s))"
  exit 1
}

Write-Host "install_check_ok"
