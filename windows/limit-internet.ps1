# ============================================================
#  limit-internet.ps1  —  one-file internet speed cap
#  For Windows 10 and Windows 11. Nothing to install.
#
#  What it enforces on THIS PC, in the background, from boot:
#    * UPLOAD   (e.g. 5 KB/s)  — exact, via Windows' own QoS meter
#    * DOWNLOAD (e.g. 50 KB/s) — approximate, by shrinking the
#      TCP receive window (how much the PC accepts at once) and
#      steering browsers back to TCP. Windows has NO built-in
#      exact download cap; see windows\README.md for the honest
#      details and the exact alternative (the whoson toll booth).
#
#  HOW TO USE (one time per PC):
#    1. Copy this file to the PC, e.g.  C:\whoson\limit-internet.ps1
#    2. Right-click Start > "Terminal (Admin)" (Win 11)
#       or "Windows PowerShell (Admin)" (Win 10)
#    3. Run:
#         powershell -ExecutionPolicy Bypass -File C:\whoson\limit-internet.ps1 -Action install
#
#  OTHER ACTIONS:
#    ... -Action status     show what is currently enforced
#    ... -Action remove     undo everything, restore full speed
#
#  It runs invisibly in the background and re-applies itself at
#  every boot (hidden scheduled task, SYSTEM account).
# ============================================================

param(
    [int]$DownloadKB = 50,           # target download cap, kilobytes/sec (approximate)
    [int]$UploadKB = 5,              # upload cap, kilobytes/sec (exact)
    [string]$Action = "install"      # install | apply | status | remove
)

$ErrorActionPreference = "Stop"
$QosName   = "whoson-limit"
$TaskName  = "whoson-limit"
$FwName    = "whoson-force-tcp"
$TcpParams = "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"

# ---- download target -> TCP receive-window size -----------------
# A TCP download runs at roughly (window size / round-trip time).
# Assuming ~50 ms to typical servers: window = rate x 0.05 s.
# Range kept sane: 512 .. 65535 bytes.
$Window = [Math]::Min(65535, [Math]::Max(512, [int]($DownloadKB * 1024 * 0.05)))

# ---- helpers ----------------------------------------------------
function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-Admin {
    if (-not (Test-Admin)) {
        Write-Host "This needs Administrator. Re-launching with a UAC prompt..." -ForegroundColor Yellow
        Start-Process powershell.exe -Verb RunAs -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"",
            "-Action", $Action, "-DownloadKB", $DownloadKB, "-UploadKB", $UploadKB)
        exit
    }
}

function Set-RegDword($path, $name, $value) {
        if (-not (Test-Path $path)) { New-Item -Path $path -Force | Out-Null }
        Set-ItemProperty -Path $path -Name $name -Value $value -Type DWord
}

function Apply-Everything {
    # 1) UPLOAD cap — exact, built-in QoS meter ("5KB" = 5 kilobytes/s)
    Remove-NetQosPolicy -Name $QosName -ErrorAction SilentlyContinue
    New-NetQosPolicy -Name $QosName -Default `
        -ThrottleRateActionBitsPerSecond "$($UploadKB)KB" | Out-Null

    # 2) DOWNLOAD cap — approximate, two levers:
    #    a) stop Windows auto-growing the receive window, then pin it small
    netsh int tcp set global autotuninglevel=disabled | Out-Null
    Set-RegDword $TcpParams "GlobalMaxTcpWindowSize" $Window
    Set-RegDword $TcpParams "TcpWindowSize" $Window
    Set-RegDword $TcpParams "Tcp1323Opts" 1   # window scaling OFF so the pin holds
    #    b) block QUIC (browsers' UDP shortcut) so downloads use TCP,
    #       which the small window slows. Reversible; removed by -Action remove.
    if (-not (Get-NetFirewallRule -DisplayName $FwName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $FwName -Direction Outbound `
            -Action Block -Protocol UDP -RemotePort 443 | Out-Null
    }
}

# ---- actions ----------------------------------------------------
switch ($Action.ToLower()) {

    "install" {
        Assert-Admin
        # hidden background re-application at every boot, as SYSTEM
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        $args_ = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" " +
                 "-Action apply -DownloadKB $DownloadKB -UploadKB $UploadKB"
        Register-ScheduledTask -TaskName $TaskName `
            -Action    (New-ScheduledTaskAction -Execute "powershell.exe" -Argument $args_) `
            -Trigger   (New-ScheduledTaskTrigger -AtStartup) `
            -User "SYSTEM" -RunLevel Highest | Out-Null
        Apply-Everything
        Write-Host "Done. This PC is now capped in the background:" -ForegroundColor Green
        Write-Host "  upload   : $UploadKB KB/s  (exact)"
        Write-Host "  download : about $DownloadKB KB/s  (approximate - TCP receive-window method)"
        Write-Host "  re-applied automatically at every boot"
        Write-Host "Undo any time with:  -Action remove"
    }

    "apply" {
        # boot-time path (hidden); also safe to run manually
        Apply-Everything
    }

    "status" {
        $qos = Get-NetQosPolicy -Name $QosName -ErrorAction SilentlyContinue
        if ($qos) {
            $kb = [Math]::Round($qos.ThrottleRateActionBitsPerSecond / 8 / 1KB)
            Write-Host "Upload cap   : $kb KB/s (active)"
        } else {
            Write-Host "Upload cap   : not set"
        }
        $auto = (netsh int tcp show global) | Select-String "Receive Window Auto-Tuning"
        Write-Host ("Auto-tuning  : " + $(if ($auto) { $auto.ToString().Trim() } else { "unknown" }))
        if (Test-Path $TcpParams) {
            $w = (Get-ItemProperty $TcpParams -ErrorAction SilentlyContinue).TcpWindowSize
            Write-Host ("Pinned window: " + $(if ($w) { "$w bytes (download ~$([int]($w/0.05/1024)) KB/s)" } else { "not pinned" }))
        }
        $fw = Get-NetFirewallRule -DisplayName $FwName -ErrorAction SilentlyContinue
        Write-Host ("QUIC blocked : " + $(if ($fw) { "yes (forces browsers onto the slowed TCP)" } else { "no" }))
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host ("Boot task    : " + $(if ($task) { "installed" } else { "not installed" }))
    }

    "remove" {
        Assert-Admin
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Remove-NetQosPolicy -Name $QosName -ErrorAction SilentlyContinue
        Remove-NetFirewallRule -DisplayName $FwName -ErrorAction SilentlyContinue
        netsh int tcp set global autotuninglevel=normal | Out-Null
        Remove-ItemProperty -Path $TcpParams -Name "GlobalMaxTcpWindowSize" -ErrorAction SilentlyContinue
        Remove-ItemProperty -Path $TcpParams -Name "TcpWindowSize" -ErrorAction SilentlyContinue
        Remove-ItemProperty -Path $TcpParams -Name "Tcp1323Opts" -ErrorAction SilentlyContinue
        Write-Host "Everything removed. This PC is back to full speed." -ForegroundColor Green
    }

    default {
        Write-Host "Unknown action '$Action'. Use: install | status | remove"
        exit 1
    }
}
