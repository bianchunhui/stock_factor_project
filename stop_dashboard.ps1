# stop_dashboard.ps1
# Stop the Streamlit dashboard started by start_dashboard.ps1.
# Kills the process tree by pid file, then by command-line fallback.
# Usage:  .\stop_dashboard.ps1

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir
$pidFile = Join-Path $scriptDir ".dashboard.pid"

if (Test-Path $pidFile) {
    $pidv = [int](Get-Content $pidFile -TotalCount 1)
    Write-Host ("Killing pid " + $pidv + " ...") -ForegroundColor Cyan
    taskkill.exe /F /T /PID $pidv 2>$null
    Remove-Item $pidFile -Force
}

# Fallback: kill any python still running our app.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*streamlit_app.py*" } |
    ForEach-Object {
        Write-Host ("Killing leftover pid " + $_.ProcessId) -ForegroundColor Cyan
        taskkill.exe /F /T /PID $_.ProcessId 2>$null
    }

Write-Host "Dashboard stopped." -ForegroundColor Yellow
