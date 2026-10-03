param([string]$Config)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$root = Split-Path -Parent $PSScriptRoot
$status = Invoke-StripControl -Root $root -Action '--status' -Config $Config
if ($status.running) { Write-Host 'Codex Usage Strip is already running.'; exit 0 }
if (-not $status.codex_available) { throw $status.codex_error }
$launch = Get-StripLaunch -Root $root
$arguments = @($launch.Arguments)
if ($Config) { $arguments += @('--config', [IO.Path]::GetFullPath($Config)) }
$start = @{ FilePath = $launch.Executable; WindowStyle = 'Hidden'; PassThru = $true }
if ($arguments.Count) { $start.ArgumentList = Join-StripArguments $arguments }
$process = Start-Process @start
Write-Host 'Codex Usage Strip started. Open Codex to see the quota cards.'
