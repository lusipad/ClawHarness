param(
  [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$ComposeFile = (Resolve-Path "$PSScriptRoot\..\rocketchat-local\compose.yml").Path,
  [string]$RootUrl = "http://127.0.0.1:3000",
  [string]$ChannelName = "ai-dev",
  [string]$IntegrationName = "ClawHarness",
  [switch]$ResetData
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-RandomSecret([int]$Length = 24) {
  $alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
  $chars = New-Object char[] $Length
  $bytes = New-Object byte[] $Length
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $rng.GetBytes($bytes)
  } finally {
    $rng.Dispose()
  }
  for ($i = 0; $i -lt $Length; $i++) {
    $chars[$i] = $alphabet[$bytes[$i] % $alphabet.Length]
  }
  return -join $chars
}

function Set-UserEnvDefault([string]$Name, [string]$DefaultValue) {
  $value = [Environment]::GetEnvironmentVariable($Name, "User")
  if (-not $value) {
    $value = $DefaultValue
    [Environment]::SetEnvironmentVariable($Name, $value, "User")
    Write-Host "Created user environment variable $Name."
  }
  Set-Item -Path ("Env:" + $Name) -Value $value
  return $value
}

function Read-ErrorResponseContent($Response) {
  if (-not $Response) {
    return ""
  }
  $stream = $Response.GetResponseStream()
  if (-not $stream) {
    return ""
  }
  try {
    $reader = New-Object System.IO.StreamReader($stream)
    try {
      return $reader.ReadToEnd()
    } finally {
      $reader.Dispose()
    }
  } finally {
    $stream.Dispose()
  }
}

function Invoke-JsonRequest {
  param(
    [Parameter(Mandatory = $true)][string]$Method,
    [Parameter(Mandatory = $true)][string]$Uri,
    [hashtable]$Headers,
    $Body
  )

  $params = @{
    Uri = $Uri
    Method = $Method
    UseBasicParsing = $true
  }
  if ($Headers) {
    $params.Headers = $Headers
  }
  if ($PSBoundParameters.ContainsKey("Body") -and $null -ne $Body) {
    $params.Body = ($Body | ConvertTo-Json -Depth 20 -Compress)
    $params.ContentType = "application/json"
  }

  $statusCode = 0
  $content = ""
  try {
    $response = Invoke-WebRequest @params
    $statusCode = [int]$response.StatusCode
    $content = $response.Content
  } catch {
    $response = $_.Exception.Response
    if (-not $response) {
      throw
    }
    $statusCode = [int]$response.StatusCode
    $content = Read-ErrorResponseContent $response
  }

  $json = $null
  if ($content) {
    try {
      $json = $content | ConvertFrom-Json
    } catch {
    }
  }

  return [pscustomobject]@{
    StatusCode = $statusCode
    Content = $content
    Json = $json
  }
}

function Wait-ForHttpOk([string]$Uri, [int]$TimeoutSeconds = 600) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 15
      if ([int]$response.StatusCode -eq 200) {
        return
      }
    } catch {
    }
    Start-Sleep -Seconds 5
  }
  throw "Timed out waiting for $Uri"
}

function Wait-ForRocketChatLogin([string]$BaseUrl, [string]$Username, [string]$Password) {
  $deadline = (Get-Date).AddMinutes(10)
  while ((Get-Date) -lt $deadline) {
    $login = Invoke-JsonRequest -Method "POST" -Uri "$BaseUrl/api/v1/login" -Body @{
      user = $Username
      password = $Password
    }
    if ($login.StatusCode -lt 400 -and $login.Json -and $login.Json.status -eq "success") {
      $authToken = $login.Json.data.authToken
      $userId = $login.Json.data.userId
      if ($authToken -and $userId) {
        return @{
          "X-Auth-Token" = $authToken
          "X-User-Id" = $userId
        }
      }
    }
    Start-Sleep -Seconds 5
  }
  throw "Timed out waiting for Rocket.Chat administrator login to become available."
}

function Ensure-ApiSuccess($Response, [string]$Action) {
  if ($Response.StatusCode -ge 400) {
    throw "$Action failed with status $($Response.StatusCode): $($Response.Content)"
  }
  if ($Response.Json -and $Response.Json.PSObject.Properties.Name -contains "success" -and -not $Response.Json.success) {
    throw "$Action failed: $($Response.Content)"
  }
}

function Join-BaseUrl([string]$BaseUrl, [string]$Path) {
  return ($BaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/"))
}

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
  throw "docker not found on PATH."
}

& $docker.Source version | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "docker engine is not reachable."
}

& $docker.Source compose version | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "docker compose is not available."
}

if ($ResetData.IsPresent) {
  Write-Host "Removing existing Rocket.Chat local containers and volumes."
  Push-Location $RepoRoot
  try {
    & $docker.Source compose -f $ComposeFile down -v
    if ($LASTEXITCODE -ne 0) {
      throw "docker compose down -v failed."
    }
  } finally {
    Pop-Location
  }
}

$release = Set-UserEnvDefault "RC_RELEASE" "8.0.1"
$rootUrl = Set-UserEnvDefault "RC_ROOT_URL" $RootUrl
$adminUsername = Set-UserEnvDefault "RC_ADMIN_USERNAME" "openclawadmin"
$adminName = Set-UserEnvDefault "RC_ADMIN_NAME" "ClawHarness Admin"
$adminEmail = Set-UserEnvDefault "RC_ADMIN_EMAIL" "clawharness-admin@local.test"
$adminPass = Set-UserEnvDefault "RC_ADMIN_PASS" (New-RandomSecret)

Write-Host "Starting local Rocket.Chat stack from $ComposeFile"
Push-Location $RepoRoot
try {
  & $docker.Source compose -f $ComposeFile up -d
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose up -d failed."
  }
} finally {
  Pop-Location
}

Wait-ForHttpOk (Join-BaseUrl $rootUrl "api/info")
$authHeaders = Wait-ForRocketChatLogin -BaseUrl $rootUrl -Username $adminUsername -Password $adminPass

$encodedChannel = [System.Uri]::EscapeDataString($ChannelName)
$roomExists = Invoke-JsonRequest -Method "GET" -Uri (Join-BaseUrl $rootUrl "api/v1/rooms.nameExists?roomName=$encodedChannel") -Headers $authHeaders
Ensure-ApiSuccess $roomExists "Checking channel existence"
if (-not $roomExists.Json.exists) {
  $createChannel = Invoke-JsonRequest -Method "POST" -Uri (Join-BaseUrl $rootUrl "api/v1/channels.create") -Headers $authHeaders -Body @{
    name = $ChannelName
  }
  Ensure-ApiSuccess $createChannel "Creating channel #$ChannelName"
}

$integrationList = Invoke-JsonRequest -Method "GET" -Uri (Join-BaseUrl $rootUrl ("api/v1/integrations.list?type=webhook-incoming&name=" + [System.Uri]::EscapeDataString($IntegrationName))) -Headers $authHeaders
Ensure-ApiSuccess $integrationList "Listing integrations"

$integration = @($integrationList.Json.integrations) | Where-Object {
  $_.name -eq $IntegrationName -and $_.type -eq "webhook-incoming"
} | Select-Object -First 1

if (-not $integration) {
  $createIntegration = Invoke-JsonRequest -Method "POST" -Uri (Join-BaseUrl $rootUrl "api/v1/integrations.create") -Headers $authHeaders -Body @{
    type = "webhook-incoming"
    username = $adminUsername
    channel = "#$ChannelName"
    scriptEnabled = $false
    name = $IntegrationName
    enabled = $true
    alias = "ClawHarness"
    emoji = ":robot_face:"
    overrideDestinationChannelEnabled = $true
  }
  Ensure-ApiSuccess $createIntegration "Creating incoming webhook integration"
  $integration = $createIntegration.Json.integration
}

$needsIntegrationUpdate = -not $integration.overrideDestinationChannelEnabled -or $integration.username -ne $adminUsername
if ($needsIntegrationUpdate) {
  $updateIntegration = Invoke-JsonRequest -Method "PUT" -Uri (Join-BaseUrl $rootUrl "api/v1/integrations.update") -Headers $authHeaders -Body @{
    integrationId = $integration._id
    type = "webhook-incoming"
    username = $adminUsername
    channel = "#$ChannelName"
    scriptEnabled = $false
    name = $IntegrationName
    enabled = $true
    alias = "ClawHarness"
    emoji = ":robot_face:"
    token = $integration.token
    overrideDestinationChannelEnabled = $true
  }
  Ensure-ApiSuccess $updateIntegration "Updating incoming webhook integration"
  $integration = $updateIntegration.Json.integration
}

if (-not $integration -or -not $integration._id -or -not $integration.token) {
  throw "Incoming webhook integration was not available after creation."
}

$webhookUrl = Join-BaseUrl $rootUrl ("hooks/{0}/{1}" -f $integration._id, $integration.token)
[Environment]::SetEnvironmentVariable("RC_WEBHOOK_URL", $webhookUrl, "User")
Set-Item -Path Env:RC_WEBHOOK_URL -Value $webhookUrl

$smokeText = "ClawHarness webhook ready " + (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
$webhookResponse = Invoke-JsonRequest -Method "POST" -Uri $webhookUrl -Body @{
  text = $smokeText
  alias = "ClawHarness"
  emoji = ":robot_face:"
}
Ensure-ApiSuccess $webhookResponse "Posting webhook smoke test"

Start-Sleep -Seconds 2
$history = Invoke-JsonRequest -Method "GET" -Uri (Join-BaseUrl $rootUrl "api/v1/channels.history?roomName=$encodedChannel&count=20") -Headers $authHeaders
Ensure-ApiSuccess $history "Reading channel history"
$matchedMessage = @($history.Json.messages) | Where-Object { $_.msg -eq $smokeText } | Select-Object -First 1
if (-not $matchedMessage) {
  throw "Webhook smoke message was accepted but was not found in #$ChannelName."
}

Write-Host "Rocket.Chat local install is ready."
Write-Host "Workspace URL: $rootUrl"
Write-Host "Admin username: $adminUsername"
Write-Host "Admin password: $adminPass"
Write-Host "Incoming webhook: $webhookUrl"
