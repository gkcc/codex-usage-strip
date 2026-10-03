param([string]$Config)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
Invoke-StripControl -Root (Split-Path -Parent $PSScriptRoot) -Action '--status' -Config $Config | ConvertTo-Json -Depth 5
