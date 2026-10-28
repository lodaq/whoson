"""Optional real UDP interoperability check; no routes are changed.
Run: python3 -m tests.check_windows_discovery --powershell /path/to/pwsh
Keep whoson closed for this check (it binds the same discovery port).
"""
import argparse
import socket, threading, subprocess, tempfile
from pathlib import Path
import companion
class Booth:
    def register_pc(self, client, ip, name, mac):
        assert ip == '127.0.0.1'
        return '127.0.0.2'
parser = argparse.ArgumentParser()
parser.add_argument('--powershell', default='pwsh')
args = parser.parse_args()
protocol=companion.Discovery('ab'*32, Booth())
sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
sock.bind(('',47831));sock.settimeout(6)
def serve():
    try:
        raw,peer=sock.recvfrom(2048)
        result=protocol.reply(raw,peer[0])
        assert result
        # Send an unauthenticated decoy first; the helper must ignore it.
        sock.sendto(b'ready|1|bad|127.0.0.9|bad',peer)
        sock.sendto(result,peer)
    finally: sock.close()
thread=threading.Thread(target=serve);thread.start()
script=r'''
$ErrorActionPreference='Stop'
$env:COMPUTERNAME='WINDOWS-TEST'
$ast=[Management.Automation.Language.Parser]::ParseFile('__SCRIPT_PATH__',[ref]$null,[ref]$null)
foreach($definition in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false)) {
 . ([scriptblock]::Create($definition.Extent.Text))
}
function Get-NetAdapter { param([switch]$Physical) [pscustomobject]@{Status='Up';InterfaceType=6;ifIndex=4;MacAddress='AA-BB-CC-DD-EE-FF'} }
function Get-NetIPAddress { param($InterfaceIndex,$AddressFamily) [pscustomobject]@{IPAddress='127.0.0.1';AddressState='Preferred';PrefixLength=8} }
$config=[pscustomobject]@{Key=('ab'*32);ClientId=('12'*16)}
$found=Find-Whoson $config
if(-not $found -or $found.Gateway -ne '127.0.0.2'){throw 'No authenticated gateway found'}
Write-Host 'PASS: PowerShell broadcasts discovery, Python verifies/registers it, PowerShell ignores decoy and verifies readiness.'
'''
source = Path(__file__).resolve().parent.parent / 'windows' / 'point-to-laptop.ps1'
script = script.replace('__SCRIPT_PATH__', str(source).replace("'", "''"))
with tempfile.NamedTemporaryFile('w',suffix='.ps1') as f:
    f.write(script);f.flush()
    p=subprocess.run([args.powershell,'-NoProfile','-File',f.name],capture_output=True,text=True,timeout=12)
    print(p.stdout,p.stderr);assert p.returncode==0
thread.join()
