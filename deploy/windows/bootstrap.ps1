param(
  [ValidateSet("docker", "native-core", "native-openclaw")]
  [string]$InstallMode = "docker",
  [ValidateSet("core", "shell", "bot-view")]
  [string]$Profile = "core",
  [ValidateSet("local-task", "azure-devops", "github")]
  [string]$ProviderProfile = "local-task",
  [string]$OpenAiApiKey,
  [string]$OpenAiBaseUrl,
  [string]$CodexModel = "gpt-5.4",
  [string]$CodexReviewModel = "gpt-5.4",
  [string]$CodexReasoningEffort = "xhigh",
  [string]$LocalRepoDir,
  [string]$LocalTasksDir,
  [string]$LocalReviewDir,
  [string]$LocalBaseBranch,
  [switch]$LocalPushEnabled,
  [string]$AdoBaseUrl,
  [string]$AdoProject,
  [string]$AdoPat,
  [string]$GitHubToken,
  [string]$GitHubWebhookSecret,
  [string]$RcWebhookUrl,
  [string]$RcCommandToken,
  [switch]$Interactive,
  [switch]$Advanced,
  [switch]$InstallDocker,
  [switch]$SkipStart,
  [switch]$CreateSampleTask
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:BootstrapBoundParameters = @{}
foreach ($entry in $PSBoundParameters.GetEnumerator()) {
  $script:BootstrapBoundParameters[$entry.Key] = $entry.Value
}
$script:WizardSelections = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)

function New-RandomHex([int]$ByteCount = 32) {
  $bytes = New-Object byte[] $ByteCount
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $rng.GetBytes($bytes)
  } finally {
    $rng.Dispose()
  }
  return -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

function Resolve-BootstrapLayout {
  $bundleCompose = Join-Path $PSScriptRoot "compose.yml"
  $bundleEnvExample = Join-Path $PSScriptRoot ".env.example"
  if ((Test-Path $bundleCompose) -and (Test-Path $bundleEnvExample)) {
    return [pscustomobject]@{
      Mode = "bundle"
      ProjectRoot = (Resolve-Path $PSScriptRoot).Path
      ComposeFile = (Resolve-Path $bundleCompose).Path
      EnvTemplate = (Resolve-Path $bundleEnvExample).Path
      EnvFile = Join-Path $PSScriptRoot ".env"
    }
  }

  $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
  $repoCompose = Join-Path $repoRoot "deploy\docker\compose.yml"
  $repoEnvExample = Join-Path $repoRoot "deploy\docker\.env.example"
  if ((Test-Path $repoCompose) -and (Test-Path $repoEnvExample)) {
    return [pscustomobject]@{
      Mode = "repo"
      ProjectRoot = $repoRoot
      ComposeFile = (Resolve-Path $repoCompose).Path
      EnvTemplate = (Resolve-Path $repoEnvExample).Path
      EnvFile = Join-Path $repoRoot "deploy\docker\.env"
    }
  }

  throw "Could not resolve bootstrap layout from $PSScriptRoot"
}

function Ensure-FileFromTemplate([string]$TargetPath, [string]$TemplatePath) {
  if (-not (Test-Path $TargetPath)) {
    Copy-Item -LiteralPath $TemplatePath -Destination $TargetPath -Force
    Write-Host "Created $TargetPath from template."
  }
}

function Set-DotEnvValue([string]$Path, [string]$Key, [string]$Value) {
  $lines = @()
  if (Test-Path $Path) {
    $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)
  }
  $pattern = '^\s*' + [regex]::Escape($Key) + '='
  $replacement = "$Key=$Value"
  $updated = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match $pattern) {
      $lines[$i] = $replacement
      $updated = $true
      break
    }
  }
  if (-not $updated) {
    $lines += $replacement
  }
  Set-Content -LiteralPath $Path -Value $lines -Encoding UTF8
}

function Get-DotEnvValue([string]$Path, [string]$Key) {
  if (-not (Test-Path $Path)) {
    return $null
  }
  $pattern = '^\s*' + [regex]::Escape($Key) + '=(.*)$'
  foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
    if ($line -match $pattern) {
      return $Matches[1]
    }
  }
  return $null
}

function Get-UserEnvValue([string]$Name) {
  return [Environment]::GetEnvironmentVariable($Name, "User")
}

function Set-UserEnvValue([string]$Name, [string]$Value) {
  $environmentRegistryPath = "HKCU:\Environment"
  if (-not (Test-Path $environmentRegistryPath)) {
    New-Item -Path $environmentRegistryPath -Force | Out-Null
  }

  if ($Value -ne "") {
    New-ItemProperty -Path $environmentRegistryPath -Name $Name -Value $Value -PropertyType String -Force | Out-Null
  } else {
    Remove-ItemProperty -Path $environmentRegistryPath -Name $Name -ErrorAction SilentlyContinue
  }

  if ($Value -ne "") {
    Set-Item -Path ("Env:" + $Name) -Value $Value
  } else {
    Remove-Item -Path ("Env:" + $Name) -ErrorAction SilentlyContinue
  }
}

function Publish-UserEnvironmentChange {
  if (-not ("ClawHarness.WindowsEnvironment" -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class WindowsEnvironment
{
    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
    public static extern IntPtr SendMessageTimeout(
        IntPtr hWnd,
        uint Msg,
        IntPtr wParam,
        string lParam,
        uint fuFlags,
        uint uTimeout,
        out IntPtr lpdwResult);
}
"@
  }

  $HWND_BROADCAST = [IntPtr]0xffff
  $WM_SETTINGCHANGE = 0x001A
  $SMTO_ABORTIFHUNG = 0x0002
  $result = [IntPtr]::Zero
  [void][WindowsEnvironment]::SendMessageTimeout(
    $HWND_BROADCAST,
    $WM_SETTINGCHANGE,
    [IntPtr]::Zero,
    "Environment",
    $SMTO_ABORTIFHUNG,
    5000,
    [ref]$result
  )
}

function Add-WizardSelections([string[]]$Names) {
  foreach ($name in $Names) {
    [void]$script:WizardSelections.Add($name)
  }
}

function Test-ValueWasProvided([string]$Name) {
  return $script:BootstrapBoundParameters.ContainsKey($Name) -or $script:WizardSelections.Contains($Name)
}

function Assert-BootstrapSelectionValid {
  if ($InstallMode -eq "native-core" -and $Profile -ne "core") {
    throw "native-core only supports -Profile core."
  }

  if ($InstallMode -eq "native-openclaw" -and $Profile -eq "bot-view") {
    throw "native-openclaw does not support -Profile bot-view. Use InstallMode=docker if you need bot-view."
  }
}

function Test-InteractiveBootstrapAvailable {
  try {
    return [Environment]::UserInteractive -and $null -ne $Host -and $null -ne $Host.UI
  } catch {
    return $false
  }
}

function Test-ShouldRunBootstrapWizard {
  if ($Advanced.IsPresent) {
    return $true
  }

  if ($Interactive.IsPresent) {
    return $true
  }

  if (-not (Test-InteractiveBootstrapAvailable)) {
    return $false
  }

  return ($script:BootstrapBoundParameters.Count -eq 0)
}

function Resolve-WizardDefault(
  [pscustomobject]$Layout,
  [string]$ParameterName,
  [string]$DotEnvKey,
  [string]$UserEnvName,
  [string]$Fallback = ""
) {
  if (Test-ValueWasProvided -Name $ParameterName) {
    return [string](Get-Variable -Name $ParameterName -Scope Script -ValueOnly)
  }

  if ($DotEnvKey) {
    $dotEnvValue = Get-DotEnvValue -Path $Layout.EnvFile -Key $DotEnvKey
    if ($null -ne $dotEnvValue -and $dotEnvValue -ne "") {
      return $dotEnvValue
    }
  }

  if ($UserEnvName) {
    $userValue = Get-UserEnvValue -Name $UserEnvName
    if ($null -ne $userValue -and $userValue -ne "") {
      return $userValue
    }
  }

  return $Fallback
}

function Read-InteractiveChoice(
  [string]$Prompt,
  [object[]]$Options,
  [string]$DefaultValue
) {
  while ($true) {
    Write-Host ""
    Write-Host $Prompt
    for ($index = 0; $index -lt $Options.Count; $index++) {
      $option = $Options[$index]
      $defaultMarker = if ($option.Value -eq $DefaultValue) { " [default]" } else { "" }
      Write-Host ("[{0}] {1}{2}" -f ($index + 1), $option.Label, $defaultMarker)
    }

    $selection = Read-Host ("Select 1-{0} or type value [{1}]" -f $Options.Count, $DefaultValue)
    if (-not $selection) {
      return $DefaultValue
    }

    if ($selection -match '^\d+$') {
      $selectedIndex = [int]$selection - 1
      if ($selectedIndex -ge 0 -and $selectedIndex -lt $Options.Count) {
        return $Options[$selectedIndex].Value
      }
    }

    foreach ($option in $Options) {
      if ($selection -eq $option.Value) {
        return $option.Value
      }
    }

    Write-Host "Invalid selection. Try again."
  }
}

function New-BootstrapWizardResult([hashtable]$Values, [string[]]$SelectedNames) {
  $Values["SelectedNames"] = $SelectedNames
  return [pscustomobject]$Values
}

function Write-WizardStepHeader(
  [int]$Step,
  [int]$Total,
  [string]$Title,
  [string]$Description = ""
) {
  Write-Host ""
  Write-Host ("Step {0}/{1}: {2}" -f $Step, $Total, $Title)
  if ($Description) {
    Write-Host $Description
  }
}

function Write-BootstrapSummary([pscustomobject]$Config) {
  Write-Host ""
  Write-Host "Install summary"
  Write-Host ("- Install mode: {0}" -f $Config.InstallMode)
  Write-Host ("- Profile: {0}" -f $Config.Profile)
  Write-Host ("- Provider: {0}" -f $Config.ProviderProfile)
  Write-Host ("- Start after install: {0}" -f $(if ($Config.SkipStart) { "no" } else { "yes" }))

  switch ($Config.ProviderProfile) {
    "local-task" {
      Write-Host ("- Local repo dir: {0}" -f $Config.LocalRepoDir)
      if ($Config.LocalTasksDir) {
        Write-Host ("- Local tasks dir: {0}" -f $Config.LocalTasksDir)
      }
      if ($Config.LocalReviewDir) {
        Write-Host ("- Local review dir: {0}" -f $Config.LocalReviewDir)
      }
      Write-Host ("- Create sample task: {0}" -f $(if ($Config.CreateSampleTask) { "yes" } else { "no" }))
    }
    "azure-devops" {
      Write-Host ("- Azure DevOps org/project: {0} / {1}" -f $Config.AdoBaseUrl, $Config.AdoProject)
    }
    "github" {
      Write-Host ("- GitHub token configured: {0}" -f $(if ($Config.GitHubToken) { "yes" } else { "no" }))
    }
  }
}

function Read-InteractiveText(
  [string]$Prompt,
  [string]$DefaultValue,
  [switch]$AllowEmpty
) {
  while ($true) {
    $suffix = if ($DefaultValue -ne "") { " [$DefaultValue]" } else { "" }
    $value = Read-Host ($Prompt + $suffix)
    if ($value -ne "") {
      return $value
    }
    if ($DefaultValue -ne "") {
      return $DefaultValue
    }
    if ($AllowEmpty.IsPresent) {
      return ""
    }
    Write-Host "Value is required."
  }
}

function Read-InteractiveYesNo(
  [string]$Prompt,
  [bool]$DefaultValue
) {
  $suffix = if ($DefaultValue) { " [Y/n]" } else { " [y/N]" }
  while ($true) {
    $value = Read-Host ($Prompt + $suffix)
    if (-not $value) {
      return $DefaultValue
    }

    switch ($value.ToLowerInvariant()) {
      "y" { return $true }
      "yes" { return $true }
      "n" { return $false }
      "no" { return $false }
    }

    Write-Host "Please answer y or n."
  }
}

function Resolve-ConfiguredValue(
  [string]$EnvPath,
  [string]$Key,
  [string]$ExplicitValue,
  [string]$DefaultValue,
  [switch]$WasExplicit
) {
  if ($WasExplicit.IsPresent) {
    return $ExplicitValue
  }

  $existingValue = Get-DotEnvValue -Path $EnvPath -Key $Key
  if ($null -ne $existingValue -and $existingValue -ne "") {
    return $existingValue
  }

  if ($null -ne $DefaultValue) {
    return $DefaultValue
  }

  return ""
}

function Resolve-ConfiguredUserValue(
  [string]$Name,
  [string]$ExplicitValue,
  [string]$DefaultValue,
  [switch]$WasExplicit
) {
  if ($WasExplicit.IsPresent) {
    return $ExplicitValue
  }

  $existingValue = Get-UserEnvValue -Name $Name
  if ($null -ne $existingValue -and $existingValue -ne "") {
    return $existingValue
  }

  if ($null -ne $DefaultValue) {
    return $DefaultValue
  }

  return ""
}

function Resolve-HostPath([string]$ProjectRoot, [string]$PathValue) {
  if (-not $PathValue) {
    return $null
  }

  if ([System.IO.Path]::IsPathRooted($PathValue)) {
    return [System.IO.Path]::GetFullPath($PathValue)
  }

  return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $PathValue))
}

function Resolve-ConfiguredHostPath(
  [string]$EnvPath,
  [string]$Key,
  [string]$ExplicitValue,
  [string]$DefaultValue,
  [string]$ProjectRoot,
  [switch]$WasExplicit
) {
  $selectedValue = Resolve-ConfiguredValue `
    -EnvPath $EnvPath `
    -Key $Key `
    -ExplicitValue $ExplicitValue `
    -DefaultValue $DefaultValue `
    -WasExplicit:$WasExplicit
  return Resolve-HostPath -ProjectRoot $ProjectRoot -PathValue $selectedValue
}

function Resolve-NativeLayout([pscustomobject]$Layout) {
  $nativeRoot = if ($Layout.Mode -eq "bundle") {
    Join-Path $Layout.ProjectRoot "src"
  } else {
    $Layout.ProjectRoot
  }

  if (-not (Test-Path $nativeRoot)) {
    throw "Native source root not found at $nativeRoot"
  }

  $windowsDir = Join-Path $nativeRoot "deploy\windows"
  if (-not (Test-Path $windowsDir)) {
    throw "Windows deployment scripts not found at $windowsDir"
  }

  return [pscustomobject]@{
    NativeRoot = $nativeRoot
    WindowsDir = $windowsDir
  }
}

function Convert-ToDockerPath([string]$PathValue) {
  return [System.IO.Path]::GetFullPath($PathValue).Replace('\', '/')
}

function Ensure-DirectoryPath([string]$PathValue) {
  if (-not (Test-Path $PathValue)) {
    New-Item -ItemType Directory -Path $PathValue -Force | Out-Null
  }
}

function Ensure-WingetPackage([string]$PackageId) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "winget is not available, so automatic prerequisite installation cannot continue."
  }
  & $winget.Source install -e --id $PackageId --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) {
    throw "winget install failed for $PackageId"
  }
}

function Ensure-CommandAvailable([string]$Name, [string]$Message) {
  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $command) {
    throw $Message
  }
  return $command
}

function Invoke-PowerShellScriptFile([string]$ScriptPath, [string[]]$ScriptArgs = @()) {
  if (-not (Test-Path $ScriptPath)) {
    throw "Script not found: $ScriptPath"
  }

  $powershell = Ensure-CommandAvailable -Name "powershell" -Message "powershell not found on PATH."
  & $powershell.Source -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @ScriptArgs
  if ($LASTEXITCODE -ne 0) {
    throw "PowerShell script failed: $ScriptPath"
  }
}

function Start-PowerShellScriptWindow([string]$ScriptPath, [string[]]$ScriptArgs = @()) {
  if (-not (Test-Path $ScriptPath)) {
    throw "Script not found: $ScriptPath"
  }

  $powershell = Ensure-CommandAvailable -Name "powershell" -Message "powershell not found on PATH."
  $argumentList = @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) + $ScriptArgs
  Start-Process -FilePath $powershell.Source -ArgumentList $argumentList | Out-Null
}

function Start-DockerDesktop {
  $candidates = @(
    (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Docker\Docker\Docker Desktop.exe")
  ) | Where-Object { $_ -and (Test-Path $_) }

  foreach ($candidate in $candidates) {
    Start-Process -FilePath $candidate | Out-Null
    Write-Host "Started Docker Desktop from $candidate"
    return
  }

  throw "Docker Desktop is installed but the launcher was not found."
}

function Wait-ForDockerEngine([string]$DockerExe, [int]$TimeoutSeconds = 180) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    & $DockerExe info *> $null
    if ($LASTEXITCODE -eq 0) {
      return
    }
    Start-Sleep -Seconds 3
  }
  throw "Docker engine is not reachable after waiting $TimeoutSeconds seconds."
}

function Ensure-Docker([switch]$AllowInstall) {
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $docker) {
    if (-not $AllowInstall.IsPresent) {
      throw "docker is not available. Re-run with -InstallDocker, or install Docker Desktop first."
    }
    Write-Host "Installing Docker Desktop with winget..."
    Ensure-WingetPackage "Docker.DockerDesktop"
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
      throw "docker is still unavailable after Docker Desktop installation."
    }
  }

  & $docker.Source compose version *> $null
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose is not available."
  }

  & $docker.Source info *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker engine is not reachable, attempting to start Docker Desktop..."
    Start-DockerDesktop
    Wait-ForDockerEngine -DockerExe $docker.Source
  }

  return $docker
}

function Wait-ForHttpOk([string]$Uri, [int]$TimeoutSeconds = 180) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 15
      if ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 400) {
        return
      }
    } catch {
    }
    Start-Sleep -Seconds 3
  }
  throw "Timed out waiting for $Uri"
}

function Start-ClawHarnessStack(
  [string]$DockerExe,
  [string]$ComposeFile,
  [string]$EnvFile,
  [string]$ProfileName
) {
  $args = @("--env-file", $EnvFile, "-f", $ComposeFile)
  if ($ProfileName -eq "shell" -or $ProfileName -eq "bot-view") {
    $args += @("--profile", "shell")
  }
  if ($ProfileName -eq "bot-view") {
    $args += @("--profile", "bot-view")
  }
  $args += @("up", "--build", "-d")
  $composeOutput = & $DockerExe compose @args 2>&1
  foreach ($line in $composeOutput) {
    Write-Host $line
  }
  if ($LASTEXITCODE -ne 0) {
    $conflictingContainers = @()
    foreach ($line in $composeOutput) {
      $text = [string]$line
      if ($text -match 'container name "/([^"]+)" is already in use') {
        $conflictingContainers += $Matches[1]
      }
    }
    if ($conflictingContainers.Count -gt 0) {
      $conflictList = ($conflictingContainers | Select-Object -Unique) -join ", "
      throw "docker compose up failed because these container names are already in use: $conflictList. The default Docker install is single-stack-per-host; stop the existing ClawHarness/OpenClaw stack or remove the conflicting containers, then rerun bootstrap."
    }
    throw "docker compose up failed."
  }
}

function Resolve-CheckInstallScriptPath([pscustomobject]$Layout) {
  if ($Layout.Mode -eq "bundle") {
    return Join-Path $Layout.ProjectRoot "check-install.ps1"
  }

  return Join-Path $Layout.ProjectRoot "deploy\windows\check-install.ps1"
}

function Invoke-FinalInstallCheck(
  [pscustomobject]$Layout,
  [string]$InstallModeValue,
  [string]$ProfileValue,
  [switch]$CheckRuntime
) {
  $checkScript = Resolve-CheckInstallScriptPath -Layout $Layout
  if (-not (Test-Path $checkScript)) {
    throw "check-install.ps1 not found at $checkScript"
  }

  Write-Host ""
  Write-Host "Running final install check..."
  $args = @("-InstallMode", $InstallModeValue)
  if ($InstallModeValue -eq "docker") {
    $args += @("-Profile", $ProfileValue)
  }
  if ($CheckRuntime.IsPresent) {
    $args += "-CheckRuntime"
  }

  Invoke-PowerShellScriptFile -ScriptPath $checkScript -ScriptArgs $args
  Write-Host "Final install check passed."
}

function Get-BootstrapFailureHints([string]$Message) {
  $hints = New-Object 'System.Collections.Generic.List[string]'
  $text = if ($Message) { $Message } else { "Unknown error." }

  if ($text -match "OPENAI_API_KEY is required") {
    $hints.Add("Provide `-OpenAiApiKey <your-key>`, or fill `OPENAI_API_KEY` in the generated .env first.") | Out-Null
  }
  if ($text -match "docker is not available") {
    $hints.Add("Install Docker Desktop first, or rerun bootstrap with `-InstallDocker`.") | Out-Null
    $hints.Add("If you only want to prepare config now, rerun with `-SkipStart`.") | Out-Null
  }
  if ($text -match "docker compose up failed") {
    $hints.Add("If another ClawHarness/OpenClaw stack is already running, stop it first, then rerun bootstrap.") | Out-Null
    $hints.Add("If you only want to write config and inspect it first, rerun with `-SkipStart`.") | Out-Null
  }
  if ($text -match "Timed out waiting for http://127.0.0.1:8080/healthz") {
    $hints.Add("The bridge did not become healthy in time. Check container logs or rerun with `-SkipStart` and start services manually.") | Out-Null
  }
  if ($text -match "Timed out waiting for http://127.0.0.1:18789/healthz") {
    $hints.Add("OpenClaw gateway did not become healthy in time. Check gateway logs or retry with the `core` profile first.") | Out-Null
  }
  if ($text -match "Timed out waiting for http://127.0.0.1:3001") {
    $hints.Add("bot-view did not become ready in time. Retry with `shell` first, then enable `bot-view` after the core services are healthy.") | Out-Null
  }
  if ($text -match "python not found on PATH") {
    $hints.Add("Install Python and make sure `python` is available on PATH, then rerun bootstrap.") | Out-Null
  }
  if ($text -match "git not found on PATH") {
    $hints.Add("Install Git and make sure `git` is available on PATH, then rerun bootstrap.") | Out-Null
  }
  if ($text -match "codex CLI not found on PATH") {
    $hints.Add("Install Codex CLI and make sure `codex` is available on PATH, then rerun bootstrap.") | Out-Null
  }
  if ($text -match "openclaw CLI not found on PATH") {
    $hints.Add("Install OpenClaw before using `native-openclaw`, or use Docker / native-core instead.") | Out-Null
  }
  if ($text -match "npm not found on PATH" -or $text -match "node not found on PATH") {
    $hints.Add("Install Node.js so both `node` and `npm` are available on PATH, then rerun bootstrap.") | Out-Null
  }
  if ($text -match "check-install.ps1 not found" -or $text -match "install_check_failed") {
    $hints.Add("The automatic verification step failed. Run `check-install.ps1` directly to see the missing prerequisite or configuration item.") | Out-Null
  }

  $hints.Add("You can always rerun bootstrap after fixing the issue; existing .env values are preserved unless you override them.") | Out-Null
  return $hints
}

function Write-BootstrapFailureSummary([System.Management.Automation.ErrorRecord]$ErrorRecord) {
  $message = if ($ErrorRecord -and $ErrorRecord.Exception) {
    $ErrorRecord.Exception.Message
  } elseif ($ErrorRecord) {
    [string]$ErrorRecord
  } else {
    "Unknown error."
  }

  Write-Host ""
  Write-Host "Installation failed"
  Write-Host ("Reason: {0}" -f $message)
  Write-Host "Common fixes:"
  foreach ($hint in Get-BootstrapFailureHints -Message $message) {
    Write-Host ("- {0}" -f $hint)
  }
}

function Ensure-SampleTask([string]$TaskDirectory) {
  Ensure-DirectoryPath $TaskDirectory
  $taskFile = Join-Path $TaskDirectory "task-001.md"
  if (-not (Test-Path $taskFile)) {
    @(
      "# Hello from ClawHarness"
      ""
      "Create or update a hello-world style change in the target repository."
      ""
      "- Add a minimal visible change."
      "- Keep the diff small."
      "- Make sure local checks still pass."
    ) | Set-Content -LiteralPath $taskFile -Encoding UTF8
    Write-Host "Created sample local task file: $taskFile"
  }
}

trap {
  Write-BootstrapFailureSummary -ErrorRecord $_
  exit 1
}

$layout = Resolve-BootstrapLayout
Ensure-FileFromTemplate -TargetPath $layout.EnvFile -TemplatePath $layout.EnvTemplate

$dataRoot = Join-Path $layout.ProjectRoot ".data"

function Invoke-QuickBootstrapWizard(
  [pscustomobject]$Layout,
  [string]$DataRoot
) {
  Write-Host ""
  Write-Host "ClawHarness quick bootstrap"
  Write-Host "This mode keeps the choices minimal. Use advanced mode if you need native install or custom directories."
  Write-Host "Press Enter to keep the default value shown in brackets."

  Write-WizardStepHeader -Step 1 -Total 4 -Title "Connection" -Description "Choose where the first tasks should come from."
  $providerProfile = Read-InteractiveChoice `
    -Prompt "What do you want to connect first" `
    -Options @(
      [pscustomobject]@{ Value = "local-task"; Label = "local-task - run against a local repository" }
      [pscustomobject]@{ Value = "azure-devops"; Label = "azure-devops - connect Azure Boards and Repos" }
      [pscustomobject]@{ Value = "github"; Label = "github - connect GitHub issues and pull requests" }
    ) `
    -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "ProviderProfile" -DotEnvKey "HARNESS_PROVIDER_PROFILE" -UserEnvName "HARNESS_PROVIDER_PROFILE" -Fallback "local-task")

  Write-WizardStepHeader -Step 2 -Total 4 -Title "Interface" -Description "Choose whether you only need the bridge or also need UI/chat layers."
  $profile = Read-InteractiveChoice `
    -Prompt "What interface do you need" `
    -Options @(
      [pscustomobject]@{ Value = "core"; Label = "core - bridge only" }
      [pscustomobject]@{ Value = "shell"; Label = "shell - add OpenClaw UI and chat host" }
      [pscustomobject]@{ Value = "bot-view"; Label = "bot-view - shell plus dashboard" }
    ) `
    -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "Profile" -DotEnvKey "" -UserEnvName "" -Fallback "core")

  $selectedNames = New-Object 'System.Collections.Generic.List[string]'
  foreach ($name in @("InstallMode", "ProviderProfile", "Profile", "OpenAiApiKey", "OpenAiBaseUrl", "InstallDocker", "SkipStart")) {
    $selectedNames.Add($name) | Out-Null
  }

  $values = [ordered]@{
    InstallMode = "docker"
    Profile = $profile
    ProviderProfile = $providerProfile
    OpenAiApiKey = $null
    OpenAiBaseUrl = $null
    InstallDocker = $false
    SkipStart = $false
    CreateSampleTask = $false
    LocalRepoDir = $null
    LocalTasksDir = $null
    LocalReviewDir = $null
    LocalBaseBranch = $null
    LocalPushEnabled = $false
    AdoBaseUrl = $null
    AdoProject = $null
    AdoPat = $null
    GitHubToken = $null
    GitHubWebhookSecret = $null
    RcWebhookUrl = $null
    RcCommandToken = $null
  }

  Write-WizardStepHeader -Step 3 -Total 4 -Title "Access And Provider Setup" -Description "Fill in the OpenAI-compatible access settings and the minimum provider data."
  $values.OpenAiApiKey = Read-InteractiveText -Prompt "OPENAI_API_KEY" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "OpenAiApiKey" -DotEnvKey "OPENAI_API_KEY" -UserEnvName "OPENAI_API_KEY" -Fallback "")
  $values.OpenAiBaseUrl = Read-InteractiveText -Prompt "OPENAI_BASE_URL (optional)" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "OpenAiBaseUrl" -DotEnvKey "OPENAI_BASE_URL" -UserEnvName "OPENAI_BASE_URL" -Fallback "") -AllowEmpty
  if ($providerProfile -eq "local-task") {
    $values.LocalRepoDir = Read-InteractiveText `
      -Prompt "Local repository directory" `
      -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "LocalRepoDir" -DotEnvKey "LOCAL_REPO_DIR" -UserEnvName "LOCAL_REPO_PATH" -Fallback (Join-Path $DataRoot "local\repo"))
    $values.LocalPushEnabled = Read-InteractiveYesNo `
      -Prompt "Allow local-task runs to push to the source repository" `
      -DefaultValue ((Resolve-WizardDefault -Layout $Layout -ParameterName "LocalPushEnabled" -DotEnvKey "LOCAL_PUSH_ENABLED" -UserEnvName "LOCAL_PUSH_ENABLED" -Fallback "0") -eq "1")
    $values.CreateSampleTask = Read-InteractiveYesNo `
      -Prompt "Create a sample local task file in the default task directory" `
      -DefaultValue $CreateSampleTask.IsPresent
    foreach ($name in @("LocalRepoDir", "LocalPushEnabled", "CreateSampleTask")) {
      $selectedNames.Add($name) | Out-Null
    }
  } elseif ($providerProfile -eq "azure-devops") {
    $values.AdoBaseUrl = Read-InteractiveText -Prompt "ADO_BASE_URL" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "AdoBaseUrl" -DotEnvKey "ADO_BASE_URL" -UserEnvName "ADO_BASE_URL" -Fallback "")
    $values.AdoProject = Read-InteractiveText -Prompt "ADO_PROJECT" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "AdoProject" -DotEnvKey "ADO_PROJECT" -UserEnvName "ADO_PROJECT" -Fallback "")
    $values.AdoPat = Read-InteractiveText -Prompt "ADO_PAT" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "AdoPat" -DotEnvKey "ADO_PAT" -UserEnvName "ADO_PAT" -Fallback "")
    foreach ($name in @("AdoBaseUrl", "AdoProject", "AdoPat")) {
      $selectedNames.Add($name) | Out-Null
    }
  } elseif ($providerProfile -eq "github") {
    $values.GitHubToken = Read-InteractiveText -Prompt "GITHUB_TOKEN" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "GitHubToken" -DotEnvKey "GITHUB_TOKEN" -UserEnvName "GITHUB_TOKEN" -Fallback "")
    $values.GitHubWebhookSecret = Read-InteractiveText -Prompt "GITHUB_WEBHOOK_SECRET (optional)" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "GitHubWebhookSecret" -DotEnvKey "GITHUB_WEBHOOK_SECRET" -UserEnvName "GITHUB_WEBHOOK_SECRET" -Fallback "") -AllowEmpty
    foreach ($name in @("GitHubToken", "GitHubWebhookSecret")) {
      $selectedNames.Add($name) | Out-Null
    }
  }

  Write-WizardStepHeader -Step 4 -Total 4 -Title "Install Behavior" -Description "Choose whether bootstrap should install Docker automatically and whether it should start services now."
  $values.InstallDocker = Read-InteractiveYesNo `
    -Prompt "Install Docker Desktop automatically with winget if docker is missing" `
    -DefaultValue $InstallDocker.IsPresent
  $values.SkipStart = -not (Read-InteractiveYesNo `
      -Prompt "Start services immediately after configuration" `
      -DefaultValue (-not $SkipStart.IsPresent))

  return New-BootstrapWizardResult -Values $values -SelectedNames $selectedNames.ToArray()
}

function Invoke-AdvancedBootstrapWizard(
  [pscustomobject]$Layout,
  [string]$DataRoot
) {
  Write-Host ""
  Write-Host "ClawHarness advanced bootstrap"
  Write-Host "Press Enter to keep the default value shown in brackets."

  Write-WizardStepHeader -Step 1 -Total 5 -Title "Install Mode" -Description "Choose Docker or one of the native install paths."
  $installMode = Read-InteractiveChoice `
    -Prompt "Select install mode" `
    -Options @(
      [pscustomobject]@{ Value = "docker"; Label = "docker - recommended one-click mode" }
      [pscustomobject]@{ Value = "native-core"; Label = "native-core - no Docker, no OpenClaw" }
      [pscustomobject]@{ Value = "native-openclaw"; Label = "native-openclaw - local OpenClaw plus bridge" }
    ) `
    -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "InstallMode" -DotEnvKey "" -UserEnvName "" -Fallback "docker")

  $profile = switch ($installMode) {
    "native-core" { "core" }
    "native-openclaw" { "shell" }
    default {
      Read-InteractiveChoice `
        -Prompt "Select runtime profile" `
        -Options @(
          [pscustomobject]@{ Value = "core"; Label = "core - bridge only" }
          [pscustomobject]@{ Value = "shell"; Label = "shell - add OpenClaw UI and chat host" }
          [pscustomobject]@{ Value = "bot-view"; Label = "bot-view - shell plus dashboard" }
        ) `
        -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "Profile" -DotEnvKey "" -UserEnvName "" -Fallback "core")
    }
  }

  Write-WizardStepHeader -Step 2 -Total 5 -Title "Provider" -Description "Choose which task system the harness should listen to first."
  $providerProfile = Read-InteractiveChoice `
    -Prompt "Select task provider" `
    -Options @(
      [pscustomobject]@{ Value = "local-task"; Label = "local-task - local repo plus local task files" }
      [pscustomobject]@{ Value = "azure-devops"; Label = "azure-devops - Azure Boards and Repos" }
      [pscustomobject]@{ Value = "github"; Label = "github - GitHub issues and pull requests" }
    ) `
    -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "ProviderProfile" -DotEnvKey "HARNESS_PROVIDER_PROFILE" -UserEnvName "HARNESS_PROVIDER_PROFILE" -Fallback "local-task")

  $localRepoDefault = Resolve-WizardDefault -Layout $Layout -ParameterName "LocalRepoDir" -DotEnvKey "LOCAL_REPO_DIR" -UserEnvName "LOCAL_REPO_PATH" -Fallback (Join-Path $DataRoot "local\repo")
  $localTasksDefault = Resolve-WizardDefault -Layout $Layout -ParameterName "LocalTasksDir" -DotEnvKey "LOCAL_TASKS_DIR" -UserEnvName "LOCAL_TASKS_PATH" -Fallback (Join-Path $DataRoot "local\tasks")
  $localReviewDefault = Resolve-WizardDefault -Layout $Layout -ParameterName "LocalReviewDir" -DotEnvKey "LOCAL_REVIEW_DIR" -UserEnvName "LOCAL_REVIEW_PATH" -Fallback (Join-Path $DataRoot "local\reviews")

  $wizard = [ordered]@{
    InstallMode = $installMode
    Profile = $profile
    ProviderProfile = $providerProfile
    OpenAiApiKey = $null
    OpenAiBaseUrl = $null
    InstallDocker = $false
    SkipStart = $false
    CreateSampleTask = $false
    LocalRepoDir = $null
    LocalTasksDir = $null
    LocalReviewDir = $null
    LocalBaseBranch = $null
    LocalPushEnabled = $false
    AdoBaseUrl = $null
    AdoProject = $null
    AdoPat = $null
    GitHubToken = $null
    GitHubWebhookSecret = $null
    RcWebhookUrl = $null
    RcCommandToken = $null
  }

  Write-WizardStepHeader -Step 3 -Total 5 -Title "Credentials" -Description "Set the OpenAI-compatible endpoint details used by Codex."
  $wizard.OpenAiApiKey = Read-InteractiveText -Prompt "OPENAI_API_KEY" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "OpenAiApiKey" -DotEnvKey "OPENAI_API_KEY" -UserEnvName "OPENAI_API_KEY" -Fallback "")
  $wizard.OpenAiBaseUrl = Read-InteractiveText -Prompt "OPENAI_BASE_URL (optional)" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "OpenAiBaseUrl" -DotEnvKey "OPENAI_BASE_URL" -UserEnvName "OPENAI_BASE_URL" -Fallback "") -AllowEmpty
  if ($providerProfile -eq "local-task") {
    Write-WizardStepHeader -Step 4 -Total 5 -Title "Local Paths" -Description "Choose where local repositories, tasks, and review output should live."
    $wizard.LocalRepoDir = Read-InteractiveText -Prompt "Local repository directory" -DefaultValue $localRepoDefault
    $wizard.LocalTasksDir = Read-InteractiveText -Prompt "Local tasks directory" -DefaultValue $localTasksDefault
    $wizard.LocalReviewDir = Read-InteractiveText -Prompt "Local review output directory" -DefaultValue $localReviewDefault
    $wizard.LocalBaseBranch = Read-InteractiveText -Prompt "Local base branch (optional)" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "LocalBaseBranch" -DotEnvKey "LOCAL_BASE_BRANCH" -UserEnvName "LOCAL_BASE_BRANCH" -Fallback "") -AllowEmpty
    $wizard.LocalPushEnabled = Read-InteractiveYesNo -Prompt "Allow local-task runs to push to the source repository" -DefaultValue ((Resolve-WizardDefault -Layout $Layout -ParameterName "LocalPushEnabled" -DotEnvKey "LOCAL_PUSH_ENABLED" -UserEnvName "LOCAL_PUSH_ENABLED" -Fallback "0") -eq "1")
    $wizard.CreateSampleTask = Read-InteractiveYesNo -Prompt "Create a sample local task file task-001.md" -DefaultValue $CreateSampleTask.IsPresent
  } elseif ($providerProfile -eq "azure-devops") {
    Write-WizardStepHeader -Step 4 -Total 5 -Title "Azure DevOps" -Description "Provide the minimum Azure DevOps connection settings."
    $wizard.AdoBaseUrl = Read-InteractiveText -Prompt "ADO_BASE_URL" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "AdoBaseUrl" -DotEnvKey "ADO_BASE_URL" -UserEnvName "ADO_BASE_URL" -Fallback "")
    $wizard.AdoProject = Read-InteractiveText -Prompt "ADO_PROJECT" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "AdoProject" -DotEnvKey "ADO_PROJECT" -UserEnvName "ADO_PROJECT" -Fallback "")
    $wizard.AdoPat = Read-InteractiveText -Prompt "ADO_PAT" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "AdoPat" -DotEnvKey "ADO_PAT" -UserEnvName "ADO_PAT" -Fallback "")
  } elseif ($providerProfile -eq "github") {
    Write-WizardStepHeader -Step 4 -Total 5 -Title "GitHub" -Description "Provide the minimum GitHub connection settings."
    $wizard.GitHubToken = Read-InteractiveText -Prompt "GITHUB_TOKEN" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "GitHubToken" -DotEnvKey "GITHUB_TOKEN" -UserEnvName "GITHUB_TOKEN" -Fallback "")
    $wizard.GitHubWebhookSecret = Read-InteractiveText -Prompt "GITHUB_WEBHOOK_SECRET (optional)" -DefaultValue (Resolve-WizardDefault -Layout $Layout -ParameterName "GitHubWebhookSecret" -DotEnvKey "GITHUB_WEBHOOK_SECRET" -UserEnvName "GITHUB_WEBHOOK_SECRET" -Fallback "") -AllowEmpty
  }

  Write-WizardStepHeader -Step 5 -Total 5 -Title "Install Behavior" -Description "Choose whether bootstrap should install Docker automatically and whether it should start services now."
  if ($installMode -eq "docker") {
    $wizard.InstallDocker = Read-InteractiveYesNo -Prompt "Install Docker Desktop automatically with winget if docker is missing" -DefaultValue $InstallDocker.IsPresent
  }
  $wizard.SkipStart = -not (Read-InteractiveYesNo -Prompt "Start services immediately after configuration" -DefaultValue (-not $SkipStart.IsPresent))

  return New-BootstrapWizardResult `
    -Values $wizard `
    -SelectedNames @(
      "InstallMode",
      "Profile",
      "ProviderProfile",
      "OpenAiApiKey",
      "OpenAiBaseUrl",
      "LocalRepoDir",
      "LocalTasksDir",
      "LocalReviewDir",
      "LocalBaseBranch",
      "LocalPushEnabled",
      "AdoBaseUrl",
      "AdoProject",
      "AdoPat",
      "GitHubToken",
      "GitHubWebhookSecret",
      "InstallDocker",
      "SkipStart",
      "CreateSampleTask"
    )
}

function Invoke-BootstrapWizard(
  [pscustomobject]$Layout,
  [string]$DataRoot
) {
  while ($true) {
    $wizardMode = if ($Advanced.IsPresent) {
      "advanced"
    } else {
      Write-WizardStepHeader -Step 0 -Total 1 -Title "Setup Experience" -Description "Choose the quick recommended flow or the full advanced flow."
      Read-InteractiveChoice `
        -Prompt "Select setup experience" `
        -Options @(
          [pscustomobject]@{ Value = "quick"; Label = "quick - recommended minimal setup" }
          [pscustomobject]@{ Value = "advanced"; Label = "advanced - expose install modes and more options" }
        ) `
        -DefaultValue "quick"
    }

    $wizardConfig = if ($wizardMode -eq "advanced") {
      Invoke-AdvancedBootstrapWizard -Layout $Layout -DataRoot $DataRoot
    } else {
      Invoke-QuickBootstrapWizard -Layout $Layout -DataRoot $DataRoot
    }

    Write-BootstrapSummary -Config $wizardConfig
    if (Read-InteractiveYesNo -Prompt "Apply this configuration" -DefaultValue $true) {
      return $wizardConfig
    }

    if ($Advanced.IsPresent) {
      Write-Host "Restarting advanced wizard..."
    } else {
      Write-Host "Restarting wizard..."
    }
  }
}

if (Test-ShouldRunBootstrapWizard) {
  $wizardConfig = Invoke-BootstrapWizard -Layout $layout -DataRoot $dataRoot

  $InstallMode = $wizardConfig.InstallMode
  $Profile = $wizardConfig.Profile
  $ProviderProfile = $wizardConfig.ProviderProfile
  $OpenAiApiKey = $wizardConfig.OpenAiApiKey
  $OpenAiBaseUrl = $wizardConfig.OpenAiBaseUrl
  $LocalRepoDir = $wizardConfig.LocalRepoDir
  $LocalTasksDir = $wizardConfig.LocalTasksDir
  $LocalReviewDir = $wizardConfig.LocalReviewDir
  $LocalBaseBranch = $wizardConfig.LocalBaseBranch
  $AdoBaseUrl = $wizardConfig.AdoBaseUrl
  $AdoProject = $wizardConfig.AdoProject
  $AdoPat = $wizardConfig.AdoPat
  $GitHubToken = $wizardConfig.GitHubToken
  $GitHubWebhookSecret = $wizardConfig.GitHubWebhookSecret

  $LocalPushEnabled = [System.Management.Automation.SwitchParameter]::new($wizardConfig.LocalPushEnabled)
  $InstallDocker = [System.Management.Automation.SwitchParameter]::new($wizardConfig.InstallDocker)
  $SkipStart = [System.Management.Automation.SwitchParameter]::new($wizardConfig.SkipStart)
  $CreateSampleTask = [System.Management.Automation.SwitchParameter]::new($wizardConfig.CreateSampleTask)

  Add-WizardSelections $wizardConfig.SelectedNames
}

Assert-BootstrapSelectionValid

$openclawDataDir = Resolve-ConfiguredHostPath `
  -EnvPath $layout.EnvFile `
  -Key "OPENCLAW_DATA_DIR" `
  -ExplicitValue "" `
  -DefaultValue (Join-Path $dataRoot "openclaw") `
  -ProjectRoot $layout.ProjectRoot `
  -WasExplicit:$false
$workspaceDir = Resolve-ConfiguredHostPath `
  -EnvPath $layout.EnvFile `
  -Key "OPENCLAW_WORKSPACE_DIR" `
  -ExplicitValue "" `
  -DefaultValue (Join-Path $dataRoot "workspace\harness") `
  -ProjectRoot $layout.ProjectRoot `
  -WasExplicit:$false
$harnessDataDir = Resolve-ConfiguredHostPath `
  -EnvPath $layout.EnvFile `
  -Key "HARNESS_DATA_DIR" `
  -ExplicitValue "" `
  -DefaultValue (Join-Path $dataRoot "harness") `
  -ProjectRoot $layout.ProjectRoot `
  -WasExplicit:$false
$localRepoHostDir = Resolve-ConfiguredHostPath `
  -EnvPath $layout.EnvFile `
  -Key "LOCAL_REPO_DIR" `
  -ExplicitValue $LocalRepoDir `
  -DefaultValue (Join-Path $dataRoot "local\repo") `
  -ProjectRoot $layout.ProjectRoot `
  -WasExplicit:$(Test-ValueWasProvided -Name "LocalRepoDir")
$localTasksHostDir = Resolve-ConfiguredHostPath `
  -EnvPath $layout.EnvFile `
  -Key "LOCAL_TASKS_DIR" `
  -ExplicitValue $LocalTasksDir `
  -DefaultValue (Join-Path $dataRoot "local\tasks") `
  -ProjectRoot $layout.ProjectRoot `
  -WasExplicit:$(Test-ValueWasProvided -Name "LocalTasksDir")
$localReviewHostDir = Resolve-ConfiguredHostPath `
  -EnvPath $layout.EnvFile `
  -Key "LOCAL_REVIEW_DIR" `
  -ExplicitValue $LocalReviewDir `
  -DefaultValue (Join-Path $dataRoot "local\reviews") `
  -ProjectRoot $layout.ProjectRoot `
  -WasExplicit:$(Test-ValueWasProvided -Name "LocalReviewDir")

Ensure-DirectoryPath $openclawDataDir
Ensure-DirectoryPath $workspaceDir
Ensure-DirectoryPath $harnessDataDir
Ensure-DirectoryPath $localRepoHostDir
Ensure-DirectoryPath $localTasksHostDir
Ensure-DirectoryPath $localReviewHostDir

if ($CreateSampleTask.IsPresent) {
  Ensure-SampleTask -TaskDirectory $localTasksHostDir
}

$existingOpenAiApiKey = Get-DotEnvValue -Path $layout.EnvFile -Key "OPENAI_API_KEY"
$existingUserOpenAiApiKey = Get-UserEnvValue -Name "OPENAI_API_KEY"
$effectiveOpenAiApiKey = if ($OpenAiApiKey) {
  $OpenAiApiKey
} elseif ($existingOpenAiApiKey) {
  $existingOpenAiApiKey
} else {
  $existingUserOpenAiApiKey
}
if (-not $effectiveOpenAiApiKey) {
  throw "OPENAI_API_KEY is required. Pass -OpenAiApiKey or fill it in $($layout.EnvFile)."
}

$effectiveProviderProfile = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "HARNESS_PROVIDER_PROFILE" `
  -ExplicitValue $ProviderProfile `
  -DefaultValue "local-task" `
  -WasExplicit:$(Test-ValueWasProvided -Name "ProviderProfile")
$effectiveExecutorBackend = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "HARNESS_EXECUTOR_BACKEND" `
  -ExplicitValue "codex-cli" `
  -DefaultValue "codex-cli" `
  -WasExplicit:$false
$effectiveLocalRepoPath = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "LOCAL_REPO_PATH" `
  -ExplicitValue "" `
  -DefaultValue "/mnt/local-repo" `
  -WasExplicit:$false
$effectiveLocalTasksPath = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "LOCAL_TASKS_PATH" `
  -ExplicitValue "" `
  -DefaultValue "/mnt/local-tasks" `
  -WasExplicit:$false
$effectiveLocalReviewPath = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "LOCAL_REVIEW_PATH" `
  -ExplicitValue "" `
  -DefaultValue "/mnt/local-reviews" `
  -WasExplicit:$false
$effectiveLocalBaseBranch = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "LOCAL_BASE_BRANCH" `
  -ExplicitValue $LocalBaseBranch `
  -DefaultValue "" `
  -WasExplicit:$(Test-ValueWasProvided -Name "LocalBaseBranch")
$effectiveLocalPushEnabled = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "LOCAL_PUSH_ENABLED" `
  -ExplicitValue $(if ($LocalPushEnabled.IsPresent) { "1" } else { "0" }) `
  -DefaultValue "0" `
  -WasExplicit:$(Test-ValueWasProvided -Name "LocalPushEnabled")
$effectiveOpenAiBaseUrl = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "OPENAI_BASE_URL" `
  -ExplicitValue $OpenAiBaseUrl `
  -DefaultValue "" `
  -WasExplicit:$(Test-ValueWasProvided -Name "OpenAiBaseUrl")
$effectiveCodexModel = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "CODEX_MODEL" `
  -ExplicitValue $CodexModel `
  -DefaultValue "gpt-5.4" `
  -WasExplicit:$(Test-ValueWasProvided -Name "CodexModel")
$effectiveCodexReviewModel = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "CODEX_REVIEW_MODEL" `
  -ExplicitValue $CodexReviewModel `
  -DefaultValue "gpt-5.4" `
  -WasExplicit:$(Test-ValueWasProvided -Name "CodexReviewModel")
$effectiveCodexReasoningEffort = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "CODEX_REASONING_EFFORT" `
  -ExplicitValue $CodexReasoningEffort `
  -DefaultValue "xhigh" `
  -WasExplicit:$(Test-ValueWasProvided -Name "CodexReasoningEffort")
$effectiveAdoBaseUrl = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "ADO_BASE_URL" `
  -ExplicitValue $AdoBaseUrl `
  -DefaultValue "" `
  -WasExplicit:$(Test-ValueWasProvided -Name "AdoBaseUrl")
$effectiveAdoProject = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "ADO_PROJECT" `
  -ExplicitValue $AdoProject `
  -DefaultValue "" `
  -WasExplicit:$(Test-ValueWasProvided -Name "AdoProject")
$effectiveAdoPat = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "ADO_PAT" `
  -ExplicitValue $AdoPat `
  -DefaultValue "" `
  -WasExplicit:$(Test-ValueWasProvided -Name "AdoPat")
$effectiveGitHubToken = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "GITHUB_TOKEN" `
  -ExplicitValue $GitHubToken `
  -DefaultValue "" `
  -WasExplicit:$(Test-ValueWasProvided -Name "GitHubToken")
$effectiveGitHubWebhookSecret = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "GITHUB_WEBHOOK_SECRET" `
  -ExplicitValue $GitHubWebhookSecret `
  -DefaultValue "" `
  -WasExplicit:$(Test-ValueWasProvided -Name "GitHubWebhookSecret")
$effectiveRcWebhookUrl = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "RC_WEBHOOK_URL" `
  -ExplicitValue $RcWebhookUrl `
  -DefaultValue "" `
  -WasExplicit:$(Test-ValueWasProvided -Name "RcWebhookUrl")
$effectiveRcCommandToken = Resolve-ConfiguredValue `
  -EnvPath $layout.EnvFile `
  -Key "RC_COMMAND_TOKEN" `
  -ExplicitValue $RcCommandToken `
  -DefaultValue "" `
  -WasExplicit:$(Test-ValueWasProvided -Name "RcCommandToken")

$ingressToken = Get-DotEnvValue -Path $layout.EnvFile -Key "HARNESS_INGRESS_TOKEN"
if (-not $ingressToken) {
  $ingressToken = New-RandomHex
}

$controlToken = Get-DotEnvValue -Path $layout.EnvFile -Key "HARNESS_CONTROL_TOKEN"
$needsControlToken = ($InstallMode -eq "docker" -and $Profile -eq "bot-view")
if ($needsControlToken -and (-not $controlToken)) {
  $controlToken = New-RandomHex
}

$gatewayToken = Get-DotEnvValue -Path $layout.EnvFile -Key "OPENCLAW_GATEWAY_TOKEN"
$hooksToken = Get-DotEnvValue -Path $layout.EnvFile -Key "OPENCLAW_HOOKS_TOKEN"
$shellEnabledValue = if ($InstallMode -eq "native-openclaw") {
  "1"
} elseif ($InstallMode -eq "native-core") {
  "0"
} elseif ($Profile -eq "core") {
  "0"
} else {
  "1"
}
$needsShellTokens = ($shellEnabledValue -eq "1")
if ($needsShellTokens -and (-not $gatewayToken)) {
  $gatewayToken = New-RandomHex
}
if ($needsShellTokens -and (-not $hooksToken)) {
  $hooksToken = New-RandomHex
}

Set-DotEnvValue -Path $layout.EnvFile -Key "OPENCLAW_DATA_DIR" -Value (Convert-ToDockerPath $openclawDataDir)
Set-DotEnvValue -Path $layout.EnvFile -Key "OPENCLAW_WORKSPACE_DIR" -Value (Convert-ToDockerPath $workspaceDir)
Set-DotEnvValue -Path $layout.EnvFile -Key "HARNESS_DATA_DIR" -Value (Convert-ToDockerPath $harnessDataDir)
Set-DotEnvValue -Path $layout.EnvFile -Key "LOCAL_REPO_DIR" -Value (Convert-ToDockerPath $localRepoHostDir)
Set-DotEnvValue -Path $layout.EnvFile -Key "LOCAL_TASKS_DIR" -Value (Convert-ToDockerPath $localTasksHostDir)
Set-DotEnvValue -Path $layout.EnvFile -Key "LOCAL_REVIEW_DIR" -Value (Convert-ToDockerPath $localReviewHostDir)

Set-DotEnvValue -Path $layout.EnvFile -Key "HARNESS_PROVIDER_PROFILE" -Value $effectiveProviderProfile
Set-DotEnvValue -Path $layout.EnvFile -Key "HARNESS_SHELL_ENABLED" -Value $shellEnabledValue
Set-DotEnvValue -Path $layout.EnvFile -Key "HARNESS_EXECUTOR_BACKEND" -Value $effectiveExecutorBackend

Set-DotEnvValue -Path $layout.EnvFile -Key "LOCAL_REPO_PATH" -Value $effectiveLocalRepoPath
Set-DotEnvValue -Path $layout.EnvFile -Key "LOCAL_TASKS_PATH" -Value $effectiveLocalTasksPath
Set-DotEnvValue -Path $layout.EnvFile -Key "LOCAL_REVIEW_PATH" -Value $effectiveLocalReviewPath
Set-DotEnvValue -Path $layout.EnvFile -Key "LOCAL_BASE_BRANCH" -Value $effectiveLocalBaseBranch
Set-DotEnvValue -Path $layout.EnvFile -Key "LOCAL_PUSH_ENABLED" -Value $effectiveLocalPushEnabled

Set-DotEnvValue -Path $layout.EnvFile -Key "OPENAI_API_KEY" -Value $effectiveOpenAiApiKey
Set-DotEnvValue -Path $layout.EnvFile -Key "OPENAI_BASE_URL" -Value $effectiveOpenAiBaseUrl
Set-DotEnvValue -Path $layout.EnvFile -Key "CODEX_MODEL" -Value $effectiveCodexModel
Set-DotEnvValue -Path $layout.EnvFile -Key "CODEX_REVIEW_MODEL" -Value $effectiveCodexReviewModel
Set-DotEnvValue -Path $layout.EnvFile -Key "CODEX_REASONING_EFFORT" -Value $effectiveCodexReasoningEffort

Set-DotEnvValue -Path $layout.EnvFile -Key "HARNESS_INGRESS_TOKEN" -Value $ingressToken
Set-DotEnvValue -Path $layout.EnvFile -Key "HARNESS_CONTROL_TOKEN" -Value $controlToken
Set-DotEnvValue -Path $layout.EnvFile -Key "OPENCLAW_GATEWAY_TOKEN" -Value $gatewayToken
Set-DotEnvValue -Path $layout.EnvFile -Key "OPENCLAW_HOOKS_TOKEN" -Value $hooksToken

Set-DotEnvValue -Path $layout.EnvFile -Key "ADO_BASE_URL" -Value $effectiveAdoBaseUrl
Set-DotEnvValue -Path $layout.EnvFile -Key "ADO_PROJECT" -Value $effectiveAdoProject
Set-DotEnvValue -Path $layout.EnvFile -Key "ADO_PAT" -Value $effectiveAdoPat
Set-DotEnvValue -Path $layout.EnvFile -Key "GITHUB_TOKEN" -Value $effectiveGitHubToken
Set-DotEnvValue -Path $layout.EnvFile -Key "GITHUB_WEBHOOK_SECRET" -Value $effectiveGitHubWebhookSecret
Set-DotEnvValue -Path $layout.EnvFile -Key "RC_WEBHOOK_URL" -Value $effectiveRcWebhookUrl
Set-DotEnvValue -Path $layout.EnvFile -Key "RC_COMMAND_TOKEN" -Value $effectiveRcCommandToken

Write-Host "Bootstrap configuration written to $($layout.EnvFile)"
Write-Host "Mode: $($layout.Mode)"
Write-Host "Install mode: $InstallMode"
Write-Host "Profile: $Profile"
Write-Host "Provider: $effectiveProviderProfile"
Write-Host "Local repo dir: $localRepoHostDir"
Write-Host "Local tasks dir: $localTasksHostDir"
Write-Host "Local review dir: $localReviewHostDir"

if ($InstallMode -ne "docker") {
  $nativeLayout = Resolve-NativeLayout -Layout $layout
  $nativeProviderProfile = Resolve-ConfiguredUserValue `
    -Name "HARNESS_PROVIDER_PROFILE" `
    -ExplicitValue $ProviderProfile `
    -DefaultValue $effectiveProviderProfile `
    -WasExplicit:$(Test-ValueWasProvided -Name "ProviderProfile")
  $nativeExecutorBackend = Resolve-ConfiguredUserValue `
    -Name "HARNESS_EXECUTOR_BACKEND" `
    -ExplicitValue "codex-cli" `
    -DefaultValue $effectiveExecutorBackend `
    -WasExplicit:$false
  $nativeOpenAiApiKey = Resolve-ConfiguredUserValue `
    -Name "OPENAI_API_KEY" `
    -ExplicitValue $OpenAiApiKey `
    -DefaultValue $effectiveOpenAiApiKey `
    -WasExplicit:$(Test-ValueWasProvided -Name "OpenAiApiKey")
  $nativeOpenAiBaseUrl = Resolve-ConfiguredUserValue `
    -Name "OPENAI_BASE_URL" `
    -ExplicitValue $OpenAiBaseUrl `
    -DefaultValue $effectiveOpenAiBaseUrl `
    -WasExplicit:$(Test-ValueWasProvided -Name "OpenAiBaseUrl")
  $nativeCodexModel = Resolve-ConfiguredUserValue `
    -Name "CODEX_MODEL" `
    -ExplicitValue $CodexModel `
    -DefaultValue $effectiveCodexModel `
    -WasExplicit:$(Test-ValueWasProvided -Name "CodexModel")
  $nativeCodexReviewModel = Resolve-ConfiguredUserValue `
    -Name "CODEX_REVIEW_MODEL" `
    -ExplicitValue $CodexReviewModel `
    -DefaultValue $effectiveCodexReviewModel `
    -WasExplicit:$(Test-ValueWasProvided -Name "CodexReviewModel")
  $nativeCodexReasoningEffort = Resolve-ConfiguredUserValue `
    -Name "CODEX_REASONING_EFFORT" `
    -ExplicitValue $CodexReasoningEffort `
    -DefaultValue $effectiveCodexReasoningEffort `
    -WasExplicit:$(Test-ValueWasProvided -Name "CodexReasoningEffort")
  $nativeLocalRepoPath = Resolve-ConfiguredUserValue `
    -Name "LOCAL_REPO_PATH" `
    -ExplicitValue $LocalRepoDir `
    -DefaultValue $localRepoHostDir `
    -WasExplicit:$(Test-ValueWasProvided -Name "LocalRepoDir")
  $nativeLocalTasksPath = Resolve-ConfiguredUserValue `
    -Name "LOCAL_TASKS_PATH" `
    -ExplicitValue $LocalTasksDir `
    -DefaultValue $localTasksHostDir `
    -WasExplicit:$(Test-ValueWasProvided -Name "LocalTasksDir")
  $nativeLocalReviewPath = Resolve-ConfiguredUserValue `
    -Name "LOCAL_REVIEW_PATH" `
    -ExplicitValue $LocalReviewDir `
    -DefaultValue $localReviewHostDir `
    -WasExplicit:$(Test-ValueWasProvided -Name "LocalReviewDir")
  $nativeLocalBaseBranch = Resolve-ConfiguredUserValue `
    -Name "LOCAL_BASE_BRANCH" `
    -ExplicitValue $LocalBaseBranch `
    -DefaultValue $effectiveLocalBaseBranch `
    -WasExplicit:$(Test-ValueWasProvided -Name "LocalBaseBranch")
  $nativeLocalPushEnabled = Resolve-ConfiguredUserValue `
    -Name "LOCAL_PUSH_ENABLED" `
    -ExplicitValue $(if ($LocalPushEnabled.IsPresent) { "1" } else { "0" }) `
    -DefaultValue $effectiveLocalPushEnabled `
    -WasExplicit:$(Test-ValueWasProvided -Name "LocalPushEnabled")
  $nativeAdoBaseUrl = Resolve-ConfiguredUserValue `
    -Name "ADO_BASE_URL" `
    -ExplicitValue $AdoBaseUrl `
    -DefaultValue $effectiveAdoBaseUrl `
    -WasExplicit:$(Test-ValueWasProvided -Name "AdoBaseUrl")
  $nativeAdoProject = Resolve-ConfiguredUserValue `
    -Name "ADO_PROJECT" `
    -ExplicitValue $AdoProject `
    -DefaultValue $effectiveAdoProject `
    -WasExplicit:$(Test-ValueWasProvided -Name "AdoProject")
  $nativeAdoPat = Resolve-ConfiguredUserValue `
    -Name "ADO_PAT" `
    -ExplicitValue $AdoPat `
    -DefaultValue $effectiveAdoPat `
    -WasExplicit:$(Test-ValueWasProvided -Name "AdoPat")
  $nativeGitHubToken = Resolve-ConfiguredUserValue `
    -Name "GITHUB_TOKEN" `
    -ExplicitValue $GitHubToken `
    -DefaultValue $effectiveGitHubToken `
    -WasExplicit:$(Test-ValueWasProvided -Name "GitHubToken")
  $nativeGitHubWebhookSecret = Resolve-ConfiguredUserValue `
    -Name "GITHUB_WEBHOOK_SECRET" `
    -ExplicitValue $GitHubWebhookSecret `
    -DefaultValue $effectiveGitHubWebhookSecret `
    -WasExplicit:$(Test-ValueWasProvided -Name "GitHubWebhookSecret")
  $nativeRcWebhookUrl = Resolve-ConfiguredUserValue `
    -Name "RC_WEBHOOK_URL" `
    -ExplicitValue $RcWebhookUrl `
    -DefaultValue $effectiveRcWebhookUrl `
    -WasExplicit:$(Test-ValueWasProvided -Name "RcWebhookUrl")
  $nativeRcCommandToken = Resolve-ConfiguredUserValue `
    -Name "RC_COMMAND_TOKEN" `
    -ExplicitValue $RcCommandToken `
    -DefaultValue $effectiveRcCommandToken `
    -WasExplicit:$(Test-ValueWasProvided -Name "RcCommandToken")

  Set-UserEnvValue -Name "OPENAI_API_KEY" -Value $nativeOpenAiApiKey
  Set-UserEnvValue -Name "OPENAI_BASE_URL" -Value $nativeOpenAiBaseUrl
  Set-UserEnvValue -Name "CODEX_MODEL" -Value $nativeCodexModel
  Set-UserEnvValue -Name "CODEX_REVIEW_MODEL" -Value $nativeCodexReviewModel
  Set-UserEnvValue -Name "CODEX_REASONING_EFFORT" -Value $nativeCodexReasoningEffort
  Set-UserEnvValue -Name "HARNESS_PROVIDER_PROFILE" -Value $nativeProviderProfile
  Set-UserEnvValue -Name "HARNESS_EXECUTOR_BACKEND" -Value $nativeExecutorBackend
  Set-UserEnvValue -Name "HARNESS_SHELL_ENABLED" -Value $shellEnabledValue
  Set-UserEnvValue -Name "HARNESS_INGRESS_TOKEN" -Value $ingressToken
  Set-UserEnvValue -Name "HARNESS_CONTROL_TOKEN" -Value $controlToken
  Set-UserEnvValue -Name "HARNESS_READONLY_TOKEN" -Value (Resolve-ConfiguredUserValue -Name "HARNESS_READONLY_TOKEN" -ExplicitValue "" -DefaultValue "" -WasExplicit:$false)
  Set-UserEnvValue -Name "LOCAL_REPO_PATH" -Value $nativeLocalRepoPath
  Set-UserEnvValue -Name "LOCAL_TASKS_PATH" -Value $nativeLocalTasksPath
  Set-UserEnvValue -Name "LOCAL_REVIEW_PATH" -Value $nativeLocalReviewPath
  Set-UserEnvValue -Name "LOCAL_BASE_BRANCH" -Value $nativeLocalBaseBranch
  Set-UserEnvValue -Name "LOCAL_PUSH_ENABLED" -Value $nativeLocalPushEnabled
  Set-UserEnvValue -Name "ADO_BASE_URL" -Value $nativeAdoBaseUrl
  Set-UserEnvValue -Name "ADO_PROJECT" -Value $nativeAdoProject
  Set-UserEnvValue -Name "ADO_PAT" -Value $nativeAdoPat
  Set-UserEnvValue -Name "GITHUB_TOKEN" -Value $nativeGitHubToken
  Set-UserEnvValue -Name "GITHUB_WEBHOOK_SECRET" -Value $nativeGitHubWebhookSecret
  Set-UserEnvValue -Name "RC_WEBHOOK_URL" -Value $nativeRcWebhookUrl
  Set-UserEnvValue -Name "RC_COMMAND_TOKEN" -Value $nativeRcCommandToken
  Publish-UserEnvironmentChange

  Write-Host "Native user environment variables have been updated."

  if ($InstallMode -eq "native-core") {
    Ensure-CommandAvailable -Name "python" -Message "python not found on PATH. Install Python before using InstallMode=native-core." | Out-Null
    Ensure-CommandAvailable -Name "git" -Message "git not found on PATH. Install Git before using InstallMode=native-core." | Out-Null
    Ensure-CommandAvailable -Name "codex" -Message "codex CLI not found on PATH. Install Codex CLI before using InstallMode=native-core." | Out-Null

    $runHarnessCore = Join-Path $nativeLayout.WindowsDir "run-harness-core.ps1"
    if (-not $SkipStart.IsPresent) {
      Start-PowerShellScriptWindow -ScriptPath $runHarnessCore
      Wait-ForHttpOk -Uri "http://127.0.0.1:8080/healthz"
      Invoke-FinalInstallCheck -Layout $layout -InstallModeValue "native-core" -ProfileValue "core" -CheckRuntime
      Write-Host "ClawHarness native core bootstrap completed successfully."
    } else {
      Invoke-FinalInstallCheck -Layout $layout -InstallModeValue "native-core" -ProfileValue "core"
      Write-Host "Native core configuration finished. Start it later with:"
      Write-Host "powershell -ExecutionPolicy Bypass -File `"$runHarnessCore`""
    }
    return
  }

  Ensure-CommandAvailable -Name "python" -Message "python not found on PATH. Install Python before using InstallMode=native-openclaw." | Out-Null
  Ensure-CommandAvailable -Name "git" -Message "git not found on PATH. Install Git before using InstallMode=native-openclaw." | Out-Null
  Ensure-CommandAvailable -Name "codex" -Message "codex CLI not found on PATH. Install Codex CLI before using InstallMode=native-openclaw." | Out-Null
  Ensure-CommandAvailable -Name "openclaw" -Message "openclaw CLI not found on PATH. Install OpenClaw before using InstallMode=native-openclaw." | Out-Null
  Ensure-CommandAvailable -Name "npm" -Message "npm not found on PATH. Install Node.js before using InstallMode=native-openclaw." | Out-Null
  Ensure-CommandAvailable -Name "node" -Message "node not found on PATH. Install Node.js before using InstallMode=native-openclaw." | Out-Null

  Set-UserEnvValue -Name "OPENCLAW_GATEWAY_TOKEN" -Value $gatewayToken
  Set-UserEnvValue -Name "OPENCLAW_HOOKS_TOKEN" -Value $hooksToken
  Publish-UserEnvironmentChange

  $installOpenClaw = Join-Path $nativeLayout.WindowsDir "install-openclaw.ps1"
  $runGateway = Join-Path $nativeLayout.WindowsDir "run-gateway.ps1"
  $runHarness = Join-Path $nativeLayout.WindowsDir "run-harness.ps1"

  Invoke-PowerShellScriptFile -ScriptPath $installOpenClaw

  if (-not $SkipStart.IsPresent) {
    Start-PowerShellScriptWindow -ScriptPath $runGateway
    Start-Sleep -Seconds 2
    Start-PowerShellScriptWindow -ScriptPath $runHarness
    Wait-ForHttpOk -Uri "http://127.0.0.1:18789/healthz"
    Wait-ForHttpOk -Uri "http://127.0.0.1:8080/healthz"
    Invoke-FinalInstallCheck -Layout $layout -InstallModeValue "native-openclaw" -ProfileValue "shell" -CheckRuntime
    Write-Host "ClawHarness native OpenClaw bootstrap completed successfully."
  } else {
    Invoke-FinalInstallCheck -Layout $layout -InstallModeValue "native-openclaw" -ProfileValue "shell"
    Write-Host "Native OpenClaw configuration finished. Start it later with:"
    Write-Host "powershell -ExecutionPolicy Bypass -File `"$runGateway`""
    Write-Host "powershell -ExecutionPolicy Bypass -File `"$runHarness`""
  }
  return
}

if ($InstallDocker.IsPresent -or (-not $SkipStart.IsPresent)) {
  $docker = Ensure-Docker -AllowInstall:$InstallDocker
}

if (-not $SkipStart.IsPresent) {
  Start-ClawHarnessStack -DockerExe $docker.Source -ComposeFile $layout.ComposeFile -EnvFile $layout.EnvFile -ProfileName $Profile
  Wait-ForHttpOk -Uri "http://127.0.0.1:8080/healthz"
  if ($Profile -eq "shell" -or $Profile -eq "bot-view") {
    Wait-ForHttpOk -Uri "http://127.0.0.1:18789/healthz"
  }
  if ($Profile -eq "bot-view") {
    Wait-ForHttpOk -Uri "http://127.0.0.1:3001"
  }
  Invoke-FinalInstallCheck -Layout $layout -InstallModeValue "docker" -ProfileValue $Profile -CheckRuntime
  Write-Host "ClawHarness bootstrap completed successfully."
} else {
  Write-Host "Skipped Docker startup and health checks because -SkipStart was specified."
  Invoke-FinalInstallCheck -Layout $layout -InstallModeValue "docker" -ProfileValue $Profile
  Write-Host "Bootstrap finished without starting the stack because -SkipStart was specified."
}
