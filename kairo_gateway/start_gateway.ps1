# Starts Apollo's PnC modules + Dreamview Plus (if not running) and the KAIRO gateway.
$ErrorActionPreference = 'Stop'
$container = if ($env:KAIRO_APOLLO_CONTAINER) { $env:KAIRO_APOLLO_CONTAINER } else { 'apollo_dev_kairo_it37' }
$root = Split-Path -Parent $PSScriptRoot

docker start $container | Out-Null
$running = docker exec $container pgrep -f dreamview_plus
if (-not $running) {
    Write-Host "Starting Apollo modules and Dreamview Plus in $container..."
    docker exec $container bash /apollo/start_dreamview_monitor.sh
}

$port = if ($env:KAIRO_GATEWAY_PORT) { [int]$env:KAIRO_GATEWAY_PORT } else { 8090 }
$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = (Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Write-Host "Port $port is already in use by '$owner' (PID $($listener.OwningProcess))."
    Write-Host "If that is an older KAIRO gateway it is already serving the tablet; otherwise stop it with:"
    Write-Host "  Stop-Process -Id $($listener.OwningProcess)"
    exit 1
}

Write-Host "Dreamview Plus: http://localhost:8888"
Write-Host "KAIRO gateway:  http://localhost:8090  (tablet: http://<this-pc-ip>:8090)"
Set-Location $root
python -m kairo_gateway
