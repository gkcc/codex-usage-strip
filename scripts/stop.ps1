param([string]$Config)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$result = Invoke-StripControl -Root (Split-Path -Parent $PSScriptRoot) -Action '--stop' -Config $Config
Write-Host 'This installation of Codex Usage Strip is stopped.'
