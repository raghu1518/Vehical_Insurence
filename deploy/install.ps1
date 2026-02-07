param(
    [string]$ServiceName = "multilingual-bot",
    [string]$DisplayName = "Multilingual Multi-Agent Bot",
    [string]$Host = "0.0.0.0",
    [int]$Port = 9019,
    [string]$Python = "",
    [string]$WorkingDir = ""
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = if ($WorkingDir) { $WorkingDir } else { Resolve-Path (Join-Path $scriptDir "..") }

if (-not (Test-Path $root)) {
    throw "Project root not found: $root"
}

if (-not $Python) {
    $venv = Join-Path $root ".venv"
    $pythonPath = Join-Path $venv "Scripts\python.exe"
    if (-not (Test-Path $pythonPath)) {
        Write-Host "Creating venv..."
        & python -m venv $venv
    }
    Write-Host "Installing requirements..."
    & $pythonPath -m pip install --upgrade pip
    & $pythonPath -m pip install -r (Join-Path $root "requirements.txt")
    $Python = $pythonPath
}

if (-not (Test-Path $Python)) {
    throw "Python executable not found: $Python"
}

$cmd = "cd /d `"$root`" && `"$Python`" -m uvicorn app:app --host $Host --port $Port"
$binPath = "cmd /c `"$cmd`""

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Updating existing service: $ServiceName"
    try { sc.exe stop $ServiceName | Out-Null } catch {}
    sc.exe config $ServiceName binPath= $binPath start= auto | Out-Null
} else {
    Write-Host "Creating service: $ServiceName"
    sc.exe create $ServiceName binPath= $binPath start= auto DisplayName= $DisplayName | Out-Null
}

sc.exe description $ServiceName "Multilingual bot service (uvicorn)" | Out-Null
sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/5000/restart/5000 | Out-Null

Write-Host "Starting service..."
sc.exe start $ServiceName | Out-Null

Write-Host "Service installed and running."
