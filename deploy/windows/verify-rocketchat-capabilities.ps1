param(
  [string]$RootUrl = [Environment]::GetEnvironmentVariable("RC_ROOT_URL", "User"),
  [string]$AdminUsername = [Environment]::GetEnvironmentVariable("RC_ADMIN_USERNAME", "User"),
  [string]$AdminPassword = [Environment]::GetEnvironmentVariable("RC_ADMIN_PASS", "User"),
  [string]$WebhookUrl = [Environment]::GetEnvironmentVariable("RC_WEBHOOK_URL", "User"),
  [string]$GroupChannel = "ai-dev",
  [string]$PeerUsername = "botpeer"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-JsonRequest {
  param(
    [Parameter(Mandatory = $true)][string]$Method,
    [Parameter(Mandatory = $true)][string]$Uri,
    [hashtable]$Headers,
    $Body
  )

  $params = @{
    Method = $Method
    Uri = $Uri
    UseBasicParsing = $true
  }
  if ($Headers) {
    $params.Headers = $Headers
  }
  if ($PSBoundParameters.ContainsKey("Body") -and $null -ne $Body) {
    $params.ContentType = "application/json"
    $params.Body = ($Body | ConvertTo-Json -Depth 20 -Compress)
  }
  return Invoke-RestMethod @params
}

function Join-BaseUrl([string]$BaseUrl, [string]$Path) {
  return ($BaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/"))
}

if (-not $RootUrl -or -not $AdminUsername -or -not $AdminPassword -or -not $WebhookUrl) {
  throw "RC_ROOT_URL, RC_ADMIN_USERNAME, RC_ADMIN_PASS, and RC_WEBHOOK_URL must be set."
}

$login = Invoke-JsonRequest -Method "POST" -Uri (Join-BaseUrl $RootUrl "api/v1/login") -Body @{
  user = $AdminUsername
  password = $AdminPassword
}
if ($login.status -ne "success") {
  throw "Rocket.Chat admin login failed."
}

$headers = @{
  "X-Auth-Token" = $login.data.authToken
  "X-User-Id" = $login.data.userId
}

$peerInfo = $null
try {
  $peerInfo = Invoke-JsonRequest -Method "GET" -Uri (Join-BaseUrl $RootUrl ("api/v1/users.info?username=" + $PeerUsername)) -Headers $headers
} catch {
}

if (-not $peerInfo -or -not $peerInfo.success) {
  $peerEmail = "$PeerUsername@local.test"
  $peerPassword = "BotPeer123!"
  try {
    $peerInfo = Invoke-JsonRequest -Method "POST" -Uri (Join-BaseUrl $RootUrl "api/v1/users.create") -Headers $headers -Body @{
      name = "Bot Peer"
      email = $peerEmail
      password = $peerPassword
      username = $PeerUsername
      active = $true
      verified = $true
      roles = @("user")
      joinDefaultChannels = $true
      requirePasswordChange = $false
      sendWelcomeEmail = $false
    }
  } catch {
    $peerInfo = Invoke-JsonRequest -Method "GET" -Uri (Join-BaseUrl $RootUrl ("api/v1/users.info?username=" + $PeerUsername)) -Headers $headers
  }
}

$results = [ordered]@{}

$groupText = "BOT group verify " + (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
Invoke-JsonRequest -Method "POST" -Uri $WebhookUrl -Body @{
  text = $groupText
  channel = "#$GroupChannel"
  alias = "ClawHarness"
  emoji = ":robot_face:"
} | Out-Null
Start-Sleep -Seconds 2
$groupHistory = Invoke-JsonRequest -Method "GET" -Uri (Join-BaseUrl $RootUrl ("api/v1/channels.history?roomName=$GroupChannel&count=20")) -Headers $headers
$groupMessage = @($groupHistory.messages) | Where-Object { $_.msg -eq $groupText } | Select-Object -First 1
$results.group_chat = [ordered]@{
  ok = [bool]$groupMessage
  text = $groupText
}

$dmRoom = Invoke-JsonRequest -Method "POST" -Uri (Join-BaseUrl $RootUrl "api/v1/dm.create") -Headers $headers -Body @{
  username = $PeerUsername
}
$dmText = "BOT dm verify " + (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
Invoke-JsonRequest -Method "POST" -Uri $WebhookUrl -Body @{
  text = $dmText
  channel = "@$PeerUsername"
  alias = "ClawHarness"
  emoji = ":robot_face:"
} | Out-Null
Start-Sleep -Seconds 2
$dmHistory = Invoke-JsonRequest -Method "GET" -Uri (Join-BaseUrl $RootUrl ("api/v1/dm.history?roomId=" + $dmRoom.room.rid + "&count=20")) -Headers $headers
$dmMessage = @($dmHistory.messages) | Where-Object { $_.msg -eq $dmText } | Select-Object -First 1
$results.direct_message = [ordered]@{
  ok = [bool]$dmMessage
  text = $dmText
  room_id = $dmRoom.room.rid
}

$imageUrl = "https://raw.githubusercontent.com/github/explore/main/topics/rocket-chat/rocket-chat.png"
$imageText = "BOT image verify " + (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
Invoke-JsonRequest -Method "POST" -Uri $WebhookUrl -Body @{
  text = $imageText
  channel = "#$GroupChannel"
  alias = "ClawHarness"
  emoji = ":robot_face:"
  attachments = @(
    @{
      text = "image attachment"
      image_url = $imageUrl
    }
  )
} | Out-Null
Start-Sleep -Seconds 2
$imageHistory = Invoke-JsonRequest -Method "GET" -Uri (Join-BaseUrl $RootUrl ("api/v1/channels.history?roomName=$GroupChannel&count=20")) -Headers $headers
$imageMessage = @($imageHistory.messages) | Where-Object { $_.msg -eq $imageText } | Select-Object -First 1
$imageAttachment = $null
if ($imageMessage -and $imageMessage.attachments) {
  $imageAttachment = @($imageMessage.attachments) | Where-Object { $_.image_url -eq $imageUrl } | Select-Object -First 1
}
$results.image_message = [ordered]@{
  ok = [bool]$imageAttachment
  text = $imageText
  image_url = $imageUrl
}

$commands = Invoke-JsonRequest -Method "GET" -Uri (Join-BaseUrl $RootUrl "api/v1/commands.list") -Headers $headers
$matchedCommands = @(
  @($commands.commands) |
    Where-Object { $_.command -match "openclaw|harness|claw|ado" } |
    Select-Object -ExpandProperty command
)
$results.command_runtime = [ordered]@{
  ok = [bool]($matchedCommands.Count -gt 0)
  matched_commands = @($matchedCommands)
}

$results | ConvertTo-Json -Depth 20
