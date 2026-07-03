param(
    [Parameter(Mandatory = $true)]
    [string]$RunDir,

    [string]$Model = "claude-opus-4-8",
    [string]$Effort = "medium",
    [string]$ClaudeExe = "claude",
    [string]$PythonExe = "python",
    [switch]$Force,
    [switch]$MergeAllowPartial
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$workflowRoot = $PSScriptRoot
$runDirPath = Resolve-Path $RunDir
$manifestPath = Join-Path $runDirPath "manifest.json"
if (-not (Test-Path $manifestPath)) {
    throw "Manifest not found: $manifestPath"
}

$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$parseScript = Join-Path $workflowRoot "parse_claude_p_response.py"
$mergeScript = Join-Path $workflowRoot "merge_claude_p_results.py"

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

    & $PythonExe $parseScript --run-dir $runDirPath --batch $batchIndex
    if ($LASTEXITCODE -ne 0) {
        throw "Parser failed for batch $batchLabel with exit code $LASTEXITCODE"
    }
}

$mergeArgs = @($mergeScript, "--run-dir", $runDirPath)
if ($MergeAllowPartial) {
    $mergeArgs += "--allow-partial"
}
& $PythonExe @mergeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Merge failed with exit code $LASTEXITCODE"
}
