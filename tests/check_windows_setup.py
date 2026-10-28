"""Exercise the paste command in PowerShell, without installing anything.
Run: python3 -m tests.check_windows_setup --powershell /path/to/pwsh
"""
import argparse
import subprocess
import tempfile

import companion

parser = argparse.ArgumentParser()
parser.add_argument('--powershell', default='pwsh')
args = parser.parse_args()
command = companion.setup_command('ab' * 32)
script = r'''
$ErrorActionPreference='Stop'
$script:exitCode=0
$script:called=$false
function powershell.exe {
    param([switch]$NoProfile, $ExecutionPolicy, $File, $Action)
    if ($Action -ne 'install' -or $ExecutionPolicy -ne 'Bypass') { throw 'Incorrect installer invocation' }
    $source=Get-Content -LiteralPath $File -Raw
    if (-not $source.Contains("$" + "BundledKey = '" + ('ab'*32) + "'")) { throw 'Pairing key missing' }
    $errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($File,[ref]$null,[ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    $script:temporaryFile=$File
    $script:called=$true
    $global:LASTEXITCODE=$script:exitCode
}
__COMMAND__
if (-not $script:called) { throw 'Installer was not invoked' }
if (Test-Path -LiteralPath $script:temporaryFile) { throw 'Temporary helper was not removed' }
$script:exitCode=1
$failed=$false
try { __COMMAND__ } catch {
    if ($_.Exception.Message -ne 'Windows setup did not complete.') { throw }
    $failed=$true
}
if (-not $failed) { throw 'Installer failure was not reported' }
if (Test-Path -LiteralPath $script:temporaryFile) { throw 'Temporary helper remains after failed install' }
Write-Host 'PASS: pasted command expands paired helper, invokes installation, reports failure, and cleans up.'
'''.replace('__COMMAND__', command)
with tempfile.NamedTemporaryFile('w', suffix='.ps1') as handle:
    handle.write(script)
    handle.flush()
    result = subprocess.run([args.powershell, '-NoProfile', '-File', handle.name],
                            capture_output=True, text=True, timeout=20)
    print(result.stdout, result.stderr)
    if result.returncode:
        raise SystemExit(result.returncode)
