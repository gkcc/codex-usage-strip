Set-StrictMode -Version Latest

function ConvertTo-StripArgument {
    param([AllowEmptyString()][string]$Value)
    $result = New-Object System.Text.StringBuilder
    [void]$result.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') { $slashes++; continue }
        if ($character -eq '"') {
            [void]$result.Append(('\' * (2 * $slashes + 1)))
            [void]$result.Append('"')
        } else {
            [void]$result.Append(('\' * $slashes))
            [void]$result.Append($character)
        }
        $slashes = 0
    }
    [void]$result.Append(('\' * (2 * $slashes)))
    [void]$result.Append('"')
    return $result.ToString()
}

function Join-StripArguments {
    param([string[]]$Arguments)
    return (($Arguments | ForEach-Object { ConvertTo-StripArgument $_ }) -join ' ')
}

function Test-StripPython {
    param([string]$Candidate)
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $null }
    if ($Candidate -match '\\Microsoft\\WindowsApps\\python(?:3)?\.exe$') { return $null }
    try {
        $resolved = & $Candidate -B -c "import sys; print(sys.executable) if sys.platform == 'win32' and sys.version_info >= (3, 10) else sys.exit(1)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath ([string]$resolved) -PathType Leaf)) {
            return [IO.Path]::GetFullPath([string]$resolved)
        }
    } catch { }
    return $null
}

function Find-StripPython {
    param([string]$Preferred)
    if (-not $Preferred) { $Preferred = $env:CODEX_USAGE_STRIP_PYTHON }
    if ($Preferred) {
        $found = Test-StripPython $Preferred
        if ($found) { return $found }
        throw 'CODEX_USAGE_STRIP_PYTHON must point to Python 3.10 or newer on Windows.'
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $candidate = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $candidate) {
                $found = Test-StripPython ([string]$candidate)
                if ($found) { return $found }
            }
        } catch { }
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) {
        $found = Test-StripPython $command.Source
        if ($found) { return $found }
    }
    $roots = @()
    if ($env:LOCALAPPDATA) { $roots += Join-Path $env:LOCALAPPDATA 'Programs\Python' }
    if ($env:ProgramFiles) { $roots += $env:ProgramFiles }
    foreach ($root in $roots) {
        $candidates = Get-ChildItem -LiteralPath $root -Directory -Filter 'Python*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending
        foreach ($directory in $candidates) {
            $found = Test-StripPython (Join-Path $directory.FullName 'python.exe')
            if ($found) { return $found }
        }
    }
    throw 'Python 3.10 or newer was not found. Use the packaged CodexUsageStrip.exe, or install Python for your user.'
}

function Get-StripLaunch {
    param([Parameter(Mandatory)][string]$Root, [switch]$Console, [string]$PythonExe)
    $rootPath = [IO.Path]::GetFullPath($Root)
    $exe = Join-Path $rootPath 'CodexUsageStrip.exe'
    if (Test-Path -LiteralPath $exe -PathType Leaf) {
        return [PSCustomObject]@{ Executable = $exe; Arguments = @() }
    }
    $source = Join-Path $rootPath 'main.py'
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'main.py or CodexUsageStrip.exe was not found beside the launchers.' }
    $python = Find-StripPython -Preferred $PythonExe
    if (-not $Console) {
        $windowless = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
        if (Test-Path -LiteralPath $windowless -PathType Leaf) { $python = $windowless }
    }
    return [PSCustomObject]@{ Executable = $python; Arguments = @('-B', $source) }
}

function Invoke-StripControl {
    param([Parameter(Mandatory)][string]$Root,
          [Parameter(Mandatory)][ValidateSet('--status', '--stop', '--install', '--uninstall')][string]$Action,
          [string]$Config)
    $launch = Get-StripLaunch -Root $Root -Console
    $token = [Guid]::NewGuid().ToString('N')
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    $run = Join-Path $temporaryRoot ('CodexUsageStrip-control-' + $token)
    $process = $null
    New-Item -ItemType Directory -Path $run -ErrorAction Stop | Out-Null
    try {
        @{ owner = 'CodexUsageStrip-control'; token = $token; pid = $PID } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'owner.json') -Encoding UTF8
        $output = Join-Path $run 'result.json'
        $arguments = @($launch.Arguments) + @($Action, '--output', $output)
        if ($Config) { $arguments += @('--config', [IO.Path]::GetFullPath($Config)) }
        $process = Start-Process -FilePath $launch.Executable -ArgumentList (Join-StripArguments $arguments) -WindowStyle Hidden -Wait -PassThru -ErrorAction Stop
        if (-not (Test-Path -LiteralPath $output -PathType Leaf)) { throw 'The usage-strip command did not produce a result.' }
        $result = Get-Content -LiteralPath $output -Raw | ConvertFrom-Json
        if ($process.ExitCode -ne 0) {
            if ($result.PSObject.Properties.Name -contains 'error') { throw ([string]$result.error) }
            throw ('The usage-strip command failed: ' + ($result | ConvertTo-Json -Compress))
        }
        return $result
    } finally {
        if ($process -and -not $process.HasExited) {
            $process.Kill()
            if (-not $process.WaitForExit(5000)) { throw ('Owned control process has not exited; retained ' + $run) }
        }
        $resolvedRun = [IO.Path]::GetFullPath($run)
        $prefix = $temporaryRoot + '\'
        if (-not $resolvedRun.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refused cleanup outside the owned temporary directory.' }
        $owner = Get-Content -LiteralPath (Join-Path $run 'owner.json') -Raw | ConvertFrom-Json
        if ($owner.token -ne $token) { throw ('Ownership changed; retained ' + $run) }
        Remove-Item -LiteralPath $run -Recurse -Force -ErrorAction Stop
    }
}
