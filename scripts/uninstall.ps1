param([string]$Config)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$result = Invoke-StripControl -Root (Split-Path -Parent $PSScriptRoot) -Action '--uninstall' -Config $Config
Write-Host 'This usage strip is stopped and its login entry is removed. Personal settings were preserved.'
Write-Host 'You can now delete this installation folder if you no longer need it.'
