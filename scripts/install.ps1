param([string]$Config)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$root = Split-Path -Parent $PSScriptRoot
$status = Invoke-StripControl -Root $root -Action '--status' -Config $Config
if (-not $status.codex_available) { throw $status.codex_error }
$result = Invoke-StripControl -Root $root -Action '--install' -Config $Config
Write-Host 'Login startup enabled for your Windows account. Keep this folder in its current location.'
& (Join-Path $PSScriptRoot 'start.ps1') -Config $Config
