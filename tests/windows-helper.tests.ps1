# Run with pwsh -NoProfile -File tests/windows-helper.tests.ps1 (no admin/network changes).
$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot '../resources/point-to-laptop.ps1'
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
# Load function definitions only, never the installer or watch loop.
foreach ($definition in $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $false)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
$folder = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $folder | Out-Null
$InstallDir = $folder
$StatePath = Join-Path $folder 'routes.json'
$ConfigPath = Join-Path $folder 'companion.json'
$Prefixes = @('0.0.0.0/1', '128.0.0.0/1')
$script:routes = [Collections.Generic.List[object]]::new()
$script:added = 0
$script:failOnSecondRoute = $false

function Assert($condition, $message) { if (-not $condition) { throw $message } }
function Get-NetRoute {
    param($AddressFamily, $InterfaceIndex, $DestinationPrefix, $ErrorAction)
    $script:routes.ToArray() | Where-Object { (!$InterfaceIndex -or $_.InterfaceIndex -eq $InterfaceIndex) -and
                                  (!$DestinationPrefix -or $_.DestinationPrefix -eq $DestinationPrefix) }
}
function New-NetRoute {
    param($DestinationPrefix, $InterfaceIndex, $NextHop, $RouteMetric, $PolicyStore)
    $script:added++
    if ($script:failOnSecondRoute -and $script:added -eq 2) { throw 'simulated route failure' }
    $script:routes.Add([pscustomobject]@{DestinationPrefix=$DestinationPrefix; InterfaceIndex=$InterfaceIndex;
                                        NextHop=$NextHop; RouteMetric=$RouteMetric})
}
function Remove-NetRoute {
    [CmdletBinding()]
    param([Parameter(ValueFromPipeline=$true)]$InputObject, [switch]$Confirm)
    process { [void]$script:routes.Remove($InputObject) }
}

try {
    $body = 'ready|1|34343434343434343434343434343434|192.168.1.253'
    $signature = Get-Signature $body ('ab'*32)
    Assert ($signature -eq '3dd9f82d60fa88edecc24c21678b1074b718a059485634939033d6bd3843bc0f') 'HMAC must match Python protocol vector'

    $router = [pscustomobject]@{ DestinationPrefix='0.0.0.0/0'; InterfaceIndex=4; NextHop='192.168.1.1'; RouteMetric=25 }
    $unrelated = [pscustomobject]@{ DestinationPrefix='0.0.0.0/1'; InterfaceIndex=9; NextHop='10.0.0.1'; RouteMetric=1 }
    $script:routes.Add($router)
    $script:routes.Add($unrelated)
    Set-HelperRoutes '192.168.1.253' 4
    Assert ($script:routes.Count -eq 4) 'helper adds two temporary routes'
    $script:added = 0
    Set-HelperRoutes '192.168.1.253' 4
    Assert ($script:added -eq 0) 'unchanged gateway does not interrupt routing'
    Set-HelperRoutes '192.168.1.252' 4
    Assert (@($script:routes | Where-Object NextHop -eq '192.168.1.253').Count -eq 0) 'old gateway removed after address change'
    Assert ($script:routes.Contains($router)) 'original router default remains'
    Remove-HelperRoutes
    Assert ($script:routes.Count -eq 2 -and $script:routes.Contains($unrelated)) 'fallback preserves all unrelated routes'

    $script:added=0; $script:failOnSecondRoute=$true
    try { Set-HelperRoutes '192.168.1.253' 4; throw 'expected route failure' } catch {
        Assert ($_.Exception.Message -eq 'simulated route failure') 'original route error retained'
    }
    Assert ($script:routes.Count -eq 2) 'partial installation rolls back both helper routes'
    $script:failOnSecondRoute=$false

    Save-Json $StatePath @{Gateway='192.168.1.253';InterfaceIndex=4}
    $script:routes.Add([pscustomobject]@{DestinationPrefix='0.0.0.0/1';InterfaceIndex=4;NextHop='192.168.1.253';RouteMetric=5})
    Set-HelperRoutes '192.168.1.253' 4
    Assert (@($script:routes | Where-Object NextHop -eq '192.168.1.253').Count -eq 2) 'recovers partial state after a crash'
    Remove-HelperRoutes

    Save-Json $ConfigPath @{Key=('ab'*32);ClientId=('12'*16)}
    function Find-Whoson { return $null }
    Set-HelperRoutes '192.168.1.253' 4
    Invoke-Heartbeat
    Assert ($script:routes.Count -eq 2) 'no ready heartbeat restores original routes'
    Write-Host 'PASS: protocol signature, gateway changes, fallback, idempotence, partial failure and crash recovery.'
} finally { Remove-Item $folder -Recurse -Force }
