param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
  throw "node not found on PATH."
}

$installRoot = Join-Path $env:LOCALAPPDATA "OpenClaw"
if (-not (Test-Path $installRoot)) {
  throw "OpenClaw install root not found at $installRoot"
}

$entry = Get-ChildItem -LiteralPath $installRoot -Directory -Filter "openclaw-*" |
  Sort-Object LastWriteTime -Descending |
  ForEach-Object { Join-Path $_.FullName "dist\\index.js" } |
  Where-Object { Test-Path $_ } |
  Select-Object -First 1

if (-not $entry) {
  throw "Could not resolve OpenClaw gateway entrypoint under $installRoot"
}

& $node.Source $entry gateway run
