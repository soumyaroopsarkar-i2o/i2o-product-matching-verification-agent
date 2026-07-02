param(
    [Parameter(Mandatory = $true)]
    [string]$RunDir,

    [Parameter(Mandatory = $true)]
    [string]$ParseScript,

    [Parameter(Mandatory = $true)]
    [string]$MergeScript,

    [string]$OutputWorkbook,
    [string]$Model = "claude-sonnet-4-6",
    [string]$Effort = "medium",
    [string]$ClaudeExe = "claude",
    [string]$PythonExe = "python",
    [switch]$Force,
    [switch]$AllowPartial
)

$ErrorActionPreference = "Stop"

$runDirPath = Resolve-Path $RunDir
$manifestPath = Join-Path $runDirPath "manifest.json"
if (-not (Test-Path $manifestPath)) {
    throw "Manifest not found: $manifestPath"
}

$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
foreach ($batch in $manifest.batches) {
    $batchIndex = [int]$batch.batch_index
    $batchLabel = "{0:D3}" -f $batchIndex
    $instructionPath = [string]$batch.instruction_path
    $rawResponsePath = [string]$batch.raw_response_path
    $resultPath = [string]$batch.result_path

    if ((Test-Path $resultPath) -and -not $Force) {
        Write-Host "Skipping batch $batchLabel; result cache exists."
        continue
    }

    if ((Test-Path $rawResponsePath) -and -not $Force) {
        Write-Host "Parsing cached raw response for batch $batchLabel."
    } else {
        Write-Host "Running Claude batch $batchLabel rows $($batch.row_idx_start)-$($batch.row_idx_end)."
        $rawParent = Split-Path $rawResponsePath -Parent
        New-Item -ItemType Directory -Path $rawParent -Force | Out-Null

        $instructionText = Get-Content $instructionPath -Raw
        $rawOutput = $instructionText | & $ClaudeExe -p --model $Model --effort $Effort
        $claudeExitCode = $LASTEXITCODE
        $rawOutput | Write-Output
        $rawOutput | Set-Content -Path $rawResponsePath -Encoding UTF8

        if ($claudeExitCode -ne 0) {
            throw "Claude failed for batch $batchLabel with exit code $claudeExitCode"
        }
    }

    & $PythonExe $ParseScript --run-dir $runDirPath --batch $batchIndex
    if ($LASTEXITCODE -ne 0) {
        throw "Parser failed for batch $batchLabel with exit code $LASTEXITCODE"
    }
}

$mergeArgs = @($MergeScript, "--run-dir", $runDirPath)
if ($OutputWorkbook) {
    $mergeArgs += @("--output-workbook", $OutputWorkbook)
}
if ($AllowPartial) {
    $mergeArgs += "--allow-partial"
}
& $PythonExe @mergeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Merge failed with exit code $LASTEXITCODE"
}

