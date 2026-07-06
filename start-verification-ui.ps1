param(
    [int]$FrontendPort = 5173,
    [int]$BackendPort = 5175,
    [switch]$SkipInstall,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$UiRoot = Join-Path $RepoRoot "apps\verification-ui"
$ServerDataRoot = Join-Path $UiRoot "server-data"
$LogRoot = Join-Path $ServerDataRoot "logs"
$FrontendUrl = "http://127.0.0.1:$FrontendPort"
$BackendUrl = "http://127.0.0.1:$BackendPort"

function Resolve-Tool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [string[]]$Candidates
    )

    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    throw "$Name was not found. Install $Name or run this from the Codex environment with bundled dependencies available."
}

function Test-Http {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Test-Frontend {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content -like '*<title>i2o Verification Agent</title>*'
    } catch {
        return $false
    }
}

function Test-TcpPort {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $client.Connect("127.0.0.1", $Port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Find-FreePort {
    param(
        [Parameter(Mandatory = $true)]
        [int]$StartPort
    )

    for ($port = $StartPort; $port -lt ($StartPort + 50); $port++) {
        if (-not (Test-TcpPort -Port $port)) {
            return $port
        }
    }

    throw "Could not find a free localhost port starting at $StartPort."
}

function Find-RunningFrontendPort {
    param(
        [Parameter(Mandatory = $true)]
        [int]$StartPort
    )

    for ($port = $StartPort; $port -lt ($StartPort + 50); $port++) {
        if (Test-Frontend -Url "http://127.0.0.1:$port") {
            return $port
        }
    }

    return $null
}

function Wait-Http {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-Http -Url $Url) {
            Write-Host "$Name is ready at $Url"
            return
        }
        Start-Sleep -Milliseconds 750
    } while ((Get-Date) -lt $deadline)

    throw "$Name did not become ready at $Url within $TimeoutSeconds seconds. Check logs in $LogRoot."
}

function Start-LoggedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )

    $escapedCommand = $Command.Replace("'", "''")
    $escapedWorkingDirectory = $WorkingDirectory.Replace("'", "''")
    $escapedLogPath = $LogPath.Replace("'", "''")
    $script = "Set-Location '$escapedWorkingDirectory'; & '$escapedCommand' $Arguments *> '$escapedLogPath'"

    $process = Start-Process `
        -FilePath "powershell" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $script) `
        -WindowStyle Hidden `
        -PassThru

    Write-Host "Started $Name with PID $($process.Id). Log: $LogPath"
}

if (-not (Test-Path $UiRoot)) {
    throw "UI folder not found: $UiRoot"
}

New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

$BundledRoot = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies"
$NodeExe = Resolve-Tool -Name "node" -Candidates @(
    (Join-Path $BundledRoot "node\bin\node.exe")
)
$PnpmExe = Resolve-Tool -Name "pnpm" -Candidates @(
    (Join-Path $BundledRoot "bin\pnpm.cmd")
)
$PythonExe = Resolve-Tool -Name "python" -Candidates @(
    (Join-Path $BundledRoot "python\python.exe")
)

$NodeBin = Split-Path -Parent $NodeExe
$PnpmBin = Split-Path -Parent $PnpmExe
$env:Path = "$NodeBin;$PnpmBin;$env:Path"
$env:PYTHON_EXE = $PythonExe
$env:CLAUDE_EXE = if ($env:CLAUDE_EXE) { $env:CLAUDE_EXE } else { "claude" }

if (-not (Test-Http -Url "$BackendUrl/api/health") -and (Test-TcpPort -Port $BackendPort)) {
    $BackendPort = Find-FreePort -StartPort ($BackendPort + 1)
    $BackendUrl = "http://127.0.0.1:$BackendPort"
    Write-Host "Preferred backend port is busy; using $BackendUrl"
}

if (-not (Test-Frontend -Url $FrontendUrl)) {
    $RunningFrontendPort = Find-RunningFrontendPort -StartPort $FrontendPort
    if ($RunningFrontendPort) {
        $FrontendPort = $RunningFrontendPort
        $FrontendUrl = "http://127.0.0.1:$FrontendPort"
    } elseif (Test-TcpPort -Port $FrontendPort) {
        $FrontendPort = Find-FreePort -StartPort ($FrontendPort + 1)
        $FrontendUrl = "http://127.0.0.1:$FrontendPort"
        Write-Host "Preferred frontend port is busy; using $FrontendUrl"
    }
}

if (-not $FrontendUrl.EndsWith(":$FrontendPort")) {
    $FrontendUrl = "http://127.0.0.1:$FrontendPort"
}

$env:VERIFICATION_API_PORT = [string]$BackendPort
$env:VITE_VERIFICATION_API_URL = $BackendUrl

$ViteScript = Join-Path $UiRoot "node_modules\vite\bin\vite.js"
if (-not $SkipInstall -and -not (Test-Path $ViteScript)) {
    Write-Host "Installing UI dependencies..."
    Push-Location $UiRoot
    try {
        & $PnpmExe install
        if ($LASTEXITCODE -ne 0) {
            throw "pnpm install failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path $ViteScript)) {
    throw "Vite was not found at $ViteScript. Run pnpm install in $UiRoot."
}

if (Test-Http -Url "$BackendUrl/api/health") {
    Write-Host "Backend is already running at $BackendUrl"
} else {
    Start-LoggedProcess `
        -Name "verification backend" `
        -Command $NodeExe `
        -Arguments "server.mjs" `
        -WorkingDirectory $UiRoot `
        -LogPath (Join-Path $LogRoot "backend.log")
}

Wait-Http -Name "Backend" -Url "$BackendUrl/api/health" -TimeoutSeconds 45

if (Test-Http -Url $FrontendUrl) {
    Write-Host "Frontend is already running at $FrontendUrl"
} else {
    Start-LoggedProcess `
        -Name "verification frontend" `
        -Command $NodeExe `
        -Arguments "`"$ViteScript`" --host 127.0.0.1 --port $FrontendPort --strictPort" `
        -WorkingDirectory $UiRoot `
        -LogPath (Join-Path $LogRoot "frontend.log")
}

Wait-Http -Name "Frontend" -Url $FrontendUrl -TimeoutSeconds 60

if (-not $NoBrowser) {
    Start-Process $FrontendUrl
}

Write-Host ""
Write-Host "Verification UI is ready: $FrontendUrl"
Write-Host "Backend health check: $BackendUrl/api/health"
