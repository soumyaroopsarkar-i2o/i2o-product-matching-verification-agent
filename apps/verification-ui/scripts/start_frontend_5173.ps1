param(
    [int]$Port = 5173,
    [string]$ApiUrl = "http://127.0.0.1:5175",
    [string]$NodeExe = "C:\Users\SoumyaroopSarkar\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
)

$ErrorActionPreference = "Stop"

$uiRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$serverData = Join-Path $uiRoot "server-data"
$viteScript = Join-Path $uiRoot "node_modules\vite\bin\vite.js"

New-Item -ItemType Directory -Path $serverData -Force | Out-Null

if (-not (Test-Path $NodeExe)) {
    throw "Node executable not found: $NodeExe"
}
if (-not (Test-Path $viteScript)) {
    throw "Vite script not found: $viteScript"
}

$quotedVite = '"' + $viteScript + '"'
$argumentLine = "$quotedVite --host 127.0.0.1 --port $Port --strictPort"

$processInfo = [System.Diagnostics.ProcessStartInfo]::new()
$processInfo.FileName = $NodeExe
$processInfo.Arguments = $argumentLine
$processInfo.WorkingDirectory = $uiRoot
$processInfo.CreateNoWindow = $true
$processInfo.UseShellExecute = $false

$process = [System.Diagnostics.Process]::Start($processInfo)

Write-Host "Started verification UI frontend PID $($process.Id) on http://127.0.0.1:$Port"
