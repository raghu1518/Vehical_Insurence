param(
    [string]$ServiceName = "multilingual-bot"
)

$ErrorActionPreference = "Stop"

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "Service not found: $ServiceName"
    exit 0
}

try {
    Write-Host "Stopping service..."
    sc.exe stop $ServiceName | Out-Null
} catch {}

Start-Sleep -Seconds 2

Write-Host "Deleting service..."
sc.exe delete $ServiceName | Out-Null

Write-Host "Service removed."
