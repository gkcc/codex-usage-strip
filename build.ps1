param([Parameter(Mandatory)][string]$WorkDirectory,
      [Parameter(Mandatory)][string]$OutputDirectory,
      [string]$PythonExe)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts\common.ps1')
$python = Find-StripPython -Preferred $PythonExe
& $python -B (Join-Path $PSScriptRoot 'build.py') --work-dir $WorkDirectory --output-dir $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'The release build failed. Check the build output above.' }
