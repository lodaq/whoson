# ==============================================================
#  point-to-laptop.ps1  —  send this PC's internet through the laptop
#  For Windows 10 and 11.  Nothing to install; one file.
#
#  WHY: only the *path* internet traffic takes can be slowed.  This
#  script makes the path go:  PC -> your laptop -> router.  Then the
#  laptop's whoson window caps this PC exactly, like any other device.
#
#  SAFE BY DESIGN: every 30 seconds the PC quietly checks "is the
#  laptop there?"  Laptop on  -> go through the laptop.
#  Laptop off -> go straight to the router (full speed, always online).
#
#  HOW TO USE (once, on the PC):
#    1. On the laptop: press "Cable mode: on" in the whoson window.
#       It prints an address like 192.168.1.253 -- that is the laptop.
#    2. Copy this file to the PC, open PowerShell as Administrator
#       (right-click Start > Terminal (Admin)) and run:
#         powershell -ExecutionPolicy Bypass -File point-to-laptop.ps1 -Action install -Gateway 192.168.1.253
#    3. On the laptop: type the PC's address in the Cable-PC box and
#       press "Cap PC" to choose its speed.
#
#  OTHER ACTIONS:
#    ... -Action status     show what is currently set
#    ... -Action remove     undo everything (PC back to stock full speed)
# ==============================================================

param(
    [string]$Action  = "install",   # install | apply | status | remove
    [string]$Gateway = "",          # the laptop's address, e.g. 192.168.1.253
    [string]$Router  = ""           # the router's address (found automatically)
)

$ErrorActionPreference = "Stop"
$TaskName = "whoson-point-to-laptop"

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
            "-Action", $Action, "-Gateway", $Gateway, "-Router", $Router)
        exit
    }
}

function Find-Router([string]$Exclude) {
    # The router is where the PC's current default route points -- but
    # ignore the laptop itself (on a re-install the route may already
    # point there; following it would make the "fallback" the laptop).
    $best = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
            Where-Object { $_.NextHop -and $_.NextHop -ne "0.0.0.0" -and
                           (-not $Exclude -or $_.NextHop -ne $Exclude) } |
            Sort-Object RouteMetric | Select-Object -First 1
    if ($best) {
        return $best.NextHop.ToString()
    }
    return ""
}

function Set-DefaultRoute($through) {
    # One default route, pointed at $through.  Deleting all defaults
    # first keeps Windows from being clever with two of them.
    route delete 0.0.0.0 mask 0.0.0.0 > $null 2>&1
    route -p delete 0.0.0.0 mask 0.0.0.0 > $null 2>&1
    route -p add 0.0.0.0 mask 0.0.0.0 $through metric 1 | Out-Null
    route add 0.0.0.0 mask 0.0.0.0 $through metric 1 | Out-Null
}

# ---- actions ----------------------------------------------------

switch ($Action.ToLower()) {

    "install" {
        if (-not $Gateway) {
            Write-Host "Which address is the laptop?  On the laptop, press" -ForegroundColor Red
            Write-Host "'Cable mode: on' in the whoson window -- it prints an" -ForegroundColor Red
            Write-Host "address like 192.168.1.253.  Then run again with:" -ForegroundColor Red
            Write-Host "  ... -Action install -Gateway 192.168.1.253" -ForegroundColor Red
            exit 1
        }
        Assert-Admin
        if (-not $Router) { $Router = Find-Router -Exclude $Gateway }
        if (-not $Router) {
            # most home routers live at .1 of the same street as the laptop
            $Router = ($Gateway -replace '\.\d+$', '.1')
        }

        # keep our own copy in a place the user won't move or delete:
        # the every-30-seconds helper must run even if the downloaded
        # file is cleaned out of Downloads
        $InstallDir  = Join-Path $env:ProgramData "whoson"
        $TaskScript  = Join-Path $InstallDir "point-to-laptop.ps1"
        New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
        Copy-Item -LiteralPath $PSCommandPath -Destination $TaskScript -Force

        # a hidden helper that re-checks every 30 seconds, forever
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        $args_ = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass " +
                 "-File `"$TaskScript`" -Action apply " +
                 "-Gateway $Gateway -Router $Router"
        Register-ScheduledTask -TaskName $TaskName `
            -Action  (New-ScheduledTaskAction -Execute "powershell.exe" -Argument $args_) `
            -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date) `
                        -RepetitionInterval (New-TimeSpan -Seconds 30) `
                        -RepetitionDuration (New-TimeSpan -Days 3650)) `
            -User "SYSTEM" -RunLevel Highest | Out-Null

        & $TaskScript -Action apply -Gateway $Gateway -Router $Router
        Write-Host ""
        Write-Host "Done. This PC now sends its internet through the laptop ($Gateway)." -ForegroundColor Green
        Write-Host "  laptop on  -> traffic goes through it (the laptop caps this PC)"
        Write-Host "  laptop off -> traffic falls back to the router ($Router), full speed"
        Write-Host "Undo any time with:  -Action remove"
        Write-Host ""
        Write-Host "Last step: in the laptop's window, type this PC's address" -ForegroundColor Cyan
        Write-Host "in the Cable-PC box and press Cap PC." -ForegroundColor Cyan
    }

    "apply" {
        # the hidden 30-second heartbeat: pick whoever is actually alive.
        # Only touch the route when it really needs changing — rewriting
        # it every 30 seconds would hiccup the PC's internet.
        if (-not $Gateway -or -not $Router) { exit }
        $target = if (Test-Connection -ComputerName $Gateway -Count 1 -Quiet) {
            $Gateway
        } else {
            $Router
        }
        $best = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
                Sort-Object RouteMetric | Select-Object -First 1
        if (-not $best -or $best.NextHop -ne $target) {
            Set-DefaultRoute $target
        }
    }

    "status" {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host ("Helper task : " + $(if ($task) { "installed (checks every 30 s)" } else { "not installed" }))
        if ($task) {
            $a = $task.Actions[0].Arguments
            $gw  = if ($a -match "-Gateway (\S+)")  { $Matches[1] } else { "?" }
            $rtr = if ($a -match "-Router (\S+)")   { $Matches[1] } else { "?" }
            Write-Host "Laptop      : $gw"
            Write-Host "Router      : $rtr"
            Write-Host ("Laptop seen : " + $(if (Test-Connection -ComputerName $gw -Count 1 -Quiet) { "yes - going through it" } else { "no - going through the router" }))
        }
        $best = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
                Sort-Object RouteMetric | Select-Object -First 1
        if ($best) { Write-Host "Right now   : default route via $($best.NextHop)" }
    }

    "remove" {
        Assert-Admin
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        route -p delete 0.0.0.0 mask 0.0.0.0 > $null 2>&1
        route delete 0.0.0.0 mask 0.0.0.0 > $null 2>&1
        # ask the network's own "hand-out" (DHCP) for a fresh, stock setup
        ipconfig /renew | Out-Null
        Write-Host "Everything removed. This PC is back to its stock full speed." -ForegroundColor Green
    }

    default {
        Write-Host "Unknown action '$Action'. Use: install | status | remove"
        exit 1
    }
}
