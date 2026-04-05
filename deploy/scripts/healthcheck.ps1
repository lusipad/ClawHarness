$bridgeHealth = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/healthz
$bridgeReady = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/readyz
$gatewayHealth = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18789/healthz

if ($bridgeHealth.StatusCode -ne 200 -or $bridgeReady.StatusCode -ne 200 -or $gatewayHealth.StatusCode -ne 200) {
  throw "healthcheck failed"
}

Write-Host "healthcheck_ok"
