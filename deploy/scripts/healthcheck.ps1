$bridgeHealth = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/healthz
$bridgeReady = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/readyz
$gatewayHealthy = $true

if (Get-Command docker -ErrorAction SilentlyContinue) {
  & docker inspect openclaw-gateway *> $null
  if ($LASTEXITCODE -eq 0) {
    $gatewayHealthy = $false
    try {
      $gatewayHealth = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18789/healthz
      $gatewayHealthy = ($gatewayHealth.StatusCode -eq 200)
    } catch {
      $gatewayHealthStatus = & docker inspect openclaw-gateway --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' 2>$null
      if ($LASTEXITCODE -eq 0 -and $gatewayHealthStatus.Trim() -eq 'healthy') {
        $gatewayHealthy = $true
      }
    }
  }
}

if ($bridgeHealth.StatusCode -ne 200 -or $bridgeReady.StatusCode -ne 200 -or -not $gatewayHealthy) {
  throw "healthcheck failed"
}

Write-Host "healthcheck_ok"
