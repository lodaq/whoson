# whoson companion. Save the paired installer on a flash drive,
# double-click whoson-install.cmd on Windows, and accept UAC once. Windows PowerShell 5.1+.
# Original default routes stay intact. Temporary IPv4 /1 routes select the
# laptop while it reports ready. Startup and periodic triggers run as SYSTEM.
param(
    [ValidateSet('install', 'watch', 'apply', 'status', 'remove')]
    [string]$Action = 'install'
)
$ErrorActionPreference = 'Stop'
$TaskName = 'whoson-point-to-laptop'
$InstallDir = Join-Path $env:ProgramData 'whoson'
$TaskScript = Join-Path $InstallDir 'point-to-laptop.ps1'
$ConfigPath = Join-Path $InstallDir 'companion.json'
$StatePath = Join-Path $InstallDir 'routes.json'
$BundledKey = '__WHOSON_PAIRING_KEY__'
$Prefixes = @('0.0.0.0/1', '128.0.0.0/1')

function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Action {1}' -f $PSCommandPath, $Action
        $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
        exit $process.ExitCode
    }
}

function Protect-InstallDirectory {
    if (Test-Path -LiteralPath $InstallDir) {
        $items = @((Get-Item -LiteralPath $InstallDir)) + @(Get-ChildItem -LiteralPath $InstallDir -Force -Recurse)
        foreach ($item in $items) {
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.LinkType) {
                throw 'The installation folder contains a link; remove it before installing.'
            }
        }
    }
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
        $identity = New-Object Security.Principal.SecurityIdentifier($sid)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $InstallDir -AclObject $acl
    if (Get-ChildItem -LiteralPath $InstallDir -Force) {
        & icacls.exe "$InstallDir\*" /reset /T /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not protect the installed files.' }
    }
}

function Read-Json($path) {
    if (Test-Path -LiteralPath $path) { return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }
    return $null
}

function Save-Json($path, $value) {
    $value | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$path.tmp" -Encoding UTF8
    Move-Item -LiteralPath "$path.tmp" -Destination $path -Force
}

function Get-Signature([string]$body, [string]$key) {
    $bytes = New-Object byte[] 32
    for ($i = 0; $i -lt 32; $i++) { $bytes[$i] = [Convert]::ToByte($key.Substring($i*2, 2), 16) }
    $hmac = New-Object Security.Cryptography.HMACSHA256
    try {
        $hmac.Key = $bytes
        return ([BitConverter]::ToString($hmac.ComputeHash([Text.Encoding]::ASCII.GetBytes($body)))).Replace('-', '').ToLowerInvariant()
    } finally { $hmac.Dispose() }
}

function Remove-HelperRoutes {
    $state = Read-Json $StatePath
    if ($state -and $state.Gateway -and $state.InterfaceIndex) {
        foreach ($prefix in $Prefixes) {
            Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -InterfaceIndex $state.InterfaceIndex `
                -ErrorAction SilentlyContinue | Where-Object { $_.NextHop -eq $state.Gateway -and $_.RouteMetric -eq 5 } |
                Remove-NetRoute -Confirm:$false -ErrorAction Stop
        }
    }
    if (Test-Path -LiteralPath $InstallDir) {
        Save-Json $StatePath @{ Gateway = ''; InterfaceIndex = 0 }
    }
}

function Set-HelperRoutes($gateway, $index) {
    $state = Read-Json $StatePath
    $routes = @(Get-NetRoute -AddressFamily IPv4 -InterfaceIndex $index -ErrorAction SilentlyContinue)
    $complete = @($routes | Where-Object { $_.NextHop -eq $gateway -and $_.RouteMetric -eq 5 -and $_.DestinationPrefix -in $Prefixes }).Count -eq 2
    if ($state -and $state.Gateway -eq $gateway -and $state.InterfaceIndex -eq $index -and $complete) { return }
    Remove-HelperRoutes
    $routes = @(Get-NetRoute -AddressFamily IPv4 -InterfaceIndex $index -ErrorAction SilentlyContinue)
    # Journal ownership BEFORE adding either route, including crash recovery.
    foreach ($prefix in $Prefixes) {
        if ($routes | Where-Object { $_.DestinationPrefix -eq $prefix -and $_.NextHop -eq $gateway }) {
            throw "An existing route already uses $gateway; refusing to take ownership."
        }
    }
    Save-Json $StatePath @{ Gateway = $gateway; InterfaceIndex = $index }
    try {
        foreach ($prefix in $Prefixes) {
            New-NetRoute -DestinationPrefix $prefix -InterfaceIndex $index -NextHop $gateway `
                -RouteMetric 5 -PolicyStore ActiveStore | Out-Null
        }
    } catch { Remove-HelperRoutes; throw }
}

function Find-Whoson($config) {
    # Probe each physical Ethernet interface; never route a VPN or a Wi-Fi
    # adapter by guessing which interface happens to have the lowest metric.
    foreach ($adapter in @(Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceType -eq 6 })) {
        foreach ($address in @(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 |
                Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' })) {
            $ip = [Net.IPAddress]::Parse($address.IPAddress)
            $mask = [uint32]0
            for ($bit = 0; $bit -lt $address.PrefixLength; $bit++) { $mask = $mask -bor ([uint32]1 -shl (31-$bit)) }
            $ipBytes = $ip.GetAddressBytes()
            [Array]::Reverse($ipBytes)
            $number = [BitConverter]::ToUInt32($ipBytes, 0)
            $broadcastBytes = [BitConverter]::GetBytes([uint32]($number -bor (-bnot $mask)))
            [Array]::Reverse($broadcastBytes)
            $broadcast = New-Object Net.IPAddress(,$broadcastBytes)
            $udp = New-Object Net.Sockets.UdpClient
            try {
                $udp.Client.Bind((New-Object Net.IPEndPoint($ip, 47832)))
                $udp.EnableBroadcast = $true
                $udp.Client.ReceiveTimeout = 1500
                $nonce = [Guid]::NewGuid().ToString('N')
                $stamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
                $name = ($env:COMPUTERNAME -replace '[^A-Za-z0-9_.-]', '_')
                if (-not $name) { $name = 'Windows-PC' }
                $mac = $adapter.MacAddress.Replace('-', ':').ToLowerInvariant()
                $body = "discover|1|$stamp|$nonce|$($config.ClientId)|$name|$mac|$($address.IPAddress)"
                $bytes = [Text.Encoding]::ASCII.GetBytes("$body|$(Get-Signature $body $config.Key)")
                $endpoint = New-Object Net.IPEndPoint($broadcast, 47831)
                [void]$udp.Send($bytes, $bytes.Length, $endpoint)
                $deadline = [DateTime]::UtcNow.AddSeconds(2)
                while ([DateTime]::UtcNow -lt $deadline) {
                    $remote = New-Object Net.IPEndPoint([Net.IPAddress]::Any, 0)
                    try { $reply = [Text.Encoding]::ASCII.GetString($udp.Receive([ref]$remote)) }
                    catch [Net.Sockets.SocketException] { break }
                    if ($reply.Length -gt 256 -or $remote.Port -ne 47831) { continue }
                    $parts = $reply.Split('|')
                    if ($parts.Count -ne 5 -or $parts[0] -ne 'ready' -or $parts[1] -ne '1' -or $parts[2] -ne $nonce) { continue }
                    $signed = $parts[0..3] -join '|'
                    if ($parts[4] -cne (Get-Signature $signed $config.Key)) { continue }
                    $gateway = [Net.IPAddress]::Parse($parts[3])
                    if ($gateway.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or $gateway.Equals($ip)) { continue }
                    $gatewayBytes = $gateway.GetAddressBytes()
                    [Array]::Reverse($gatewayBytes)
                    $gatewayNumber = [BitConverter]::ToUInt32($gatewayBytes, 0)
                    if (($gatewayNumber -band $mask) -ne ($number -band $mask)) { continue }
                    return @{ Gateway = $gateway.ToString(); InterfaceIndex = $adapter.ifIndex }
                }
            } catch [Net.Sockets.SocketException] {
                # Adapter disappeared, port in use, or no broadcast route.
            } finally { $udp.Dispose() }
        }
    }
    return $null
}

function Invoke-Heartbeat {
    $config = Read-Json $ConfigPath
    if (-not $config -or $config.Key -notmatch '^[a-f0-9]{64}$') { throw 'Install a paired helper first.' }
    $found = Find-Whoson $config
    if ($found) { Set-HelperRoutes $found.Gateway $found.InterfaceIndex }
    else { Remove-HelperRoutes }
    Remove-Item -LiteralPath (Join-Path $InstallDir "last-error.txt") -ErrorAction SilentlyContinue
}

switch ($Action) {
    'install' {
        Assert-Admin
        if ($BundledKey -notmatch '^[a-f0-9]{64}$') { throw 'Use the paired whoson-install.cmd file saved by the whoson app.' }
        Protect-InstallDirectory
        $oldConfig = Read-Json $ConfigPath
        $clientId = if ($oldConfig -and $oldConfig.ClientId) { $oldConfig.ClientId } else { [Guid]::NewGuid().ToString('N') }
        $oldTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($oldTask) {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            # Upgrade the old fixed-IP helper without deleting unrelated routes.
            $oldArgs = $oldTask.Actions[0].Arguments
            if ($oldArgs -match '-Gateway ([0-9.]+)') {
                $oldGateway = $Matches[1]
                foreach ($store in @('ActiveStore', 'PersistentStore')) {
                    Get-NetRoute -DestinationPrefix '0.0.0.0/0' -PolicyStore $store -ErrorAction SilentlyContinue |
                        Where-Object { $_.NextHop -eq $oldGateway } | Remove-NetRoute -Confirm:$false
                }
                if ($oldArgs -match '-Router ([0-9.]+)') {
                    $router = $Matches[1]
                    $address = Find-NetRoute -RemoteIPAddress $router -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress } | Select-Object -First 1
                    if ($address -and -not (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue)) {
                        New-NetRoute -DestinationPrefix '0.0.0.0/0' -NextHop $router -InterfaceIndex $address.InterfaceIndex -PolicyStore ActiveStore | Out-Null
                    }
                }
            }
        }
        Remove-HelperRoutes
        if ($PSCommandPath -ne $TaskScript) { Copy-Item -LiteralPath $PSCommandPath -Destination $TaskScript -Force }
        Save-Json $ConfigPath @{ Key = $BundledKey; ClientId = $clientId }
        Remove-NetFirewallRule -Name 'whoson-discovery' -ErrorAction SilentlyContinue
        New-NetFirewallRule -Name 'whoson-discovery' -DisplayName 'whoson authenticated LAN discovery' `
            -Direction Inbound -Action Allow -Protocol UDP -LocalPort 47832 -RemotePort 47831 `
            -RemoteAddress LocalSubnet -Program "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" | Out-Null
        $arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Action watch' -f $TaskScript
        $triggers = @((New-ScheduledTaskTrigger -AtStartup),
                      (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)))
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $TaskName -Force -User SYSTEM -RunLevel Highest `
            -Action (New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments) `
            -Trigger $triggers -Settings $settings | Out-Null
        Start-ScheduledTask -TaskName $TaskName
        Write-Host 'Installed. Keep cable mode on in whoson. This PC appears in its device list automatically.'
        Write-Host 'Restarting Windows needs no setup. No ready laptop = original router route.'
    }
    'watch' {
        Assert-Admin
        $mutex = New-Object Threading.Mutex($false, 'Global\whoson-companion')
        $owned = $false
        try {
            try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
            if (-not $owned) { exit }
            while ($true) {
                try { Invoke-Heartbeat }
                catch {
                    Remove-HelperRoutes
                    $_.Exception.Message | Set-Content (Join-Path $InstallDir 'last-error.txt')
                }
                Start-Sleep -Seconds 10
            }
        } finally {
            if ($owned) { Remove-HelperRoutes; $mutex.ReleaseMutex() }
            $mutex.Dispose()
        }
    }
    'apply' { Assert-Admin; Invoke-Heartbeat }
    'status' {
        Assert-Admin
        Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Select-Object TaskName, State
        $state = Read-Json $StatePath
        if ($state -and $state.Gateway) { Write-Host "Using laptop $($state.Gateway) on interface $($state.InterfaceIndex)" }
        else { Write-Host 'Using original router routes (no ready laptop).' }
        Get-Content (Join-Path $InstallDir 'last-error.txt') -ErrorAction SilentlyContinue
    }
    'remove' {
        Assert-Admin
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Remove-HelperRoutes
        Remove-NetFirewallRule -Name 'whoson-discovery' -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $ConfigPath, $StatePath, $TaskScript -Force -ErrorAction SilentlyContinue
        Write-Host 'Removed. Original router routes are unchanged.'
    }
}
