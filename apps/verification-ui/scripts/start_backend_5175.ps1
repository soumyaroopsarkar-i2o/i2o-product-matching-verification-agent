param(
    [int]$Port = 5175,
    [string]$NodeExe = "C:\Users\SoumyaroopSarkar\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
)

$ErrorActionPreference = "Stop"

$uiRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$serverScript = Join-Path $uiRoot "server.mjs"

if (-not (Test-Path $NodeExe)) {
    throw "Node executable not found: $NodeExe"
}
if (-not (Test-Path $serverScript)) {
    throw "Backend script not found: $serverScript"
}

$processInfo = [System.Diagnostics.ProcessStartInfo]::new()
$processInfo.FileName = $NodeExe
$processInfo.Arguments = '"' + $serverScript + '"'
$processInfo.WorkingDirectory = $uiRoot
$processInfo.CreateNoWindow = $true
$processInfo.UseShellExecute = $false

$process = [System.Diagnostics.Process]::Start($processInfo)

Write-Host "Started verification backend PID $($process.Id) on http://127.0.0.1:$Port"
