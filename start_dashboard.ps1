# start_dashboard.ps1
# Launch Streamlit multi-factor dashboard.
# Fix: closing the window now kills the whole process tree (incl. the streamlit
# child server that "python -m streamlit" spawns), so the service does not linger.
# Usage: run from terminal  .\start_dashboard.ps1
# Stop : Ctrl+C here, or run  .\stop_dashboard.ps1

$ErrorActionPreference = "Stop"

$pythonExe = "C:/Users/chunh/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$port    = 8501
$pidFile = Join-Path $scriptDir ".dashboard.pid"

# Kill every python process whose command line contains our app (leftover guard).
function Kill-DashboardTree {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*streamlit_app.py*" } |
        ForEach-Object {
            try { taskkill.exe /F /T /PID $_.ProcessId 2>$null } catch {}
        }
}

# 1) Clean any leftover instance from a previously closed window.
Write-Host "[cleanup] killing any leftover dashboard on port $port ..." -ForegroundColor DarkGray
Kill-DashboardTree

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Multi-Factor Stock Selection Dashboard"     -ForegroundColor Cyan
Write-Host " Port: $port"                                 -ForegroundColor Cyan
Write-Host " Open: http://localhost:$port"                -ForegroundColor Cyan
Write-Host " Stop: Ctrl+C here, or run stop_dashboard.ps1" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# 2) Start streamlit in the same window (foreground), keep the root PID.
$psi              = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName     = $pythonExe
$psi.Arguments    = "-m streamlit run scripts/streamlit_app.py --server.port $port --browser.gatherUsageStats false"
$psi.UseShellExecute     = $false
$psi.RedirectStandardOutput = $false
$psi.RedirectStandardError  = $false
$proc = [System.Diagnostics.Process]::Start($psi)
$proc.Id | Out-File -FilePath $pidFile -Encoding ascii

# 3) Register a console close / Ctrl+C handler that kills the whole process tree
#    (root + the streamlit-spawned child server), so closing the window stops it.
Add-Type -ReferencedAssemblies @("System.dll", "System.Management.dll") @"
using System;
using System.Diagnostics;
using System.Management;
using System.Runtime.InteropServices;
using System.Collections.Generic;
public class StreamlitGuard {
    public delegate bool CtrlHandler(uint ctrlType);
    [DllImport("kernel32.dll")] public static extern bool SetConsoleCtrlHandler(CtrlHandler h, bool add);
    public static int RootPid = -1;
    public static bool OnCtrl(uint ctrlType) {
        try { KillTree(RootPid); } catch {}
        return false;
    }
    static void KillTree(int pid) {
        if (pid <= 0) return;
        var all = new List<ManagementObject>();
        using (var searcher = new ManagementObjectSearcher("Select ProcessId,ParentProcessId From Win32_Process")) {
            foreach (ManagementObject mo in searcher.Get()) all.Add(mo);
        }
        var stack = new Stack<int>();
        stack.Push(pid);
        var toKill = new List<int>();
        while (stack.Count > 0) {
            int cur = stack.Pop();
            toKill.Add(cur);
            foreach (var mo in all) {
                try { if ((uint)mo["ParentProcessId"] == (uint)cur) stack.Push((int)(uint)mo["ProcessId"]); } catch {}
            }
        }
        foreach (int p in toKill) {
            try { Process.GetProcessById(p).Kill(); } catch {}
        }
    }
}
"@

[StreamlitGuard]::RootPid = $proc.Id
$handler = [StreamlitGuard+CtrlHandler]{ param([uint]$ctrlType) return [StreamlitGuard]::OnCtrl($ctrlType) }
[StreamlitGuard]::SetConsoleCtrlHandler($handler, $true) | Out-Null
$global:__streamlitGuardHandler = $handler   # keep alive for the whole session

# 4) Block until it exits; on any exit path, clean up the tree + pid file.
try {
    $proc.WaitForExit()
} finally {
    try { if (-not $proc.HasExited) { $proc.Kill() } } catch {}
    Kill-DashboardTree
    if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
}
Write-Host "`nDashboard stopped." -ForegroundColor Yellow
