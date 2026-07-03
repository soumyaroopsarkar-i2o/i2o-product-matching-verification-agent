param(
    [string]$InputWorkbook,
    [string]$OutputRoot,
    [int]$BatchSize = 100,
    [int]$RowStart = 0,
    [int]$RowLimit,
    [string]$Model = "claude-sonnet-4-6",
    [string]$Effort = "medium",
    [string]$ClaudeExe = "claude",
    [string]$PythonExe = "python",
    [switch]$Force,
    [switch]$AllowPartial
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$workflowRoot = $PSScriptRoot
if (-not $InputWorkbook) {
    $InputWorkbook = Join-Path $repoRoot "data\loreal-wmt-attributes\lorealpi_product_verification_input.xlsx"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "outputs\full_verification_runs"
}

$inputWorkbookPath = Resolve-Path $InputWorkbook
$outputRootPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputRoot)
New-Item -ItemType Directory -Path $outputRootPath -Force | Out-Null

$runId = "full_run_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$runRoot = Join-Path $outputRootPath $runId
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null

function Invoke-PythonScript {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Arguments
    )

    & $PythonExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE`: $($Arguments -join ' ')"
    }
}

function Invoke-ClaudeBatchStage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RunDir,
        [Parameter(Mandatory = $true)]
        [string]$ParseScript,
        [Parameter(Mandatory = $true)]
        [string]$MergeScript,
        [string]$OutputWorkbook
    )

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

        Invoke-PythonScript -Arguments @($ParseScript, "--run-dir", $runDirPath, "--batch", $batchIndex)
    }

    $mergeArgs = @($MergeScript, "--run-dir", $runDirPath)
    if ($OutputWorkbook) {
        $mergeArgs += @("--output-workbook", $OutputWorkbook)
    }
    if ($AllowPartial) {
        $mergeArgs += "--allow-partial"
    }
    Invoke-PythonScript -Arguments $mergeArgs
}

$prepareStage1 = Join-Path $workflowRoot "prepare_claude_p_batches.py"
$runStage1 = Join-Path $workflowRoot "run_claude_p_batches.ps1"
$prepareStage2A = Join-Path $workflowRoot "prepare_price_pair_batches.py"
$parseStage2A = Join-Path $workflowRoot "parse_price_pair_response.py"
$mergeStage2A = Join-Path $workflowRoot "merge_price_pair_results.py"
$prepareStage2B = Join-Path $workflowRoot "prepare_marketplace_outlier_batches.py"
$parseStage2B = Join-Path $workflowRoot "parse_marketplace_outlier_response.py"
$mergeStage2B = Join-Path $workflowRoot "merge_marketplace_outlier_results.py"

Write-Host "Full verification run: $runId"
Write-Host "Run root: $runRoot"

Write-Host "Stage 1: preparing product-verification batches."
$stage1PrepareArgs = @(
    $prepareStage1,
    "--input-workbook", $inputWorkbookPath,
    "--output-root", $runRoot,
    "--batch-size", $BatchSize,
    "--row-start", $RowStart,
    "--run-id", "stage1_product"
)
if ($PSBoundParameters.ContainsKey("RowLimit")) {
    $stage1PrepareArgs += @("--row-limit", $RowLimit)
}
Invoke-PythonScript -Arguments $stage1PrepareArgs

$stage1RunDir = Join-Path $runRoot "stage1_product"
Write-Host "Stage 1: running product-verification batches."
$stage1RunArgs = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $runStage1,
    "-RunDir", $stage1RunDir,
    "-Model", $Model,
    "-Effort", $Effort,
    "-ClaudeExe", $ClaudeExe,
    "-PythonExe", $PythonExe
)
if ($Force) {
    $stage1RunArgs += "-Force"
}
if ($AllowPartial) {
    $stage1RunArgs += "-MergeAllowPartial"
}
& powershell @stage1RunArgs
if ($LASTEXITCODE -ne 0) {
    throw "Stage 1 failed with exit code $LASTEXITCODE"
}

$stage1Manifest = Get-Content (Join-Path $stage1RunDir "manifest.json") -Raw | ConvertFrom-Json
$stage1Workbook = [string]$stage1Manifest.output_workbook

Write-Host "Stage 2A: preparing pairwise price-anomaly batches."
Invoke-PythonScript -Arguments @(
    $prepareStage2A,
    "--input-workbook", $stage1Workbook,
    "--output-root", $runRoot,
    "--batch-size", $BatchSize,
    "--run-id", "stage2a_pair"
)

$stage2ARunDir = Join-Path $runRoot "stage2a_pair"
$inputStem = [System.IO.Path]::GetFileNameWithoutExtension($inputWorkbookPath)
$finalDir = Join-Path $runRoot "final"
New-Item -ItemType Directory -Path $finalDir -Force | Out-Null
$stage2AWorkbook = Join-Path $finalDir ("{0}_stage2a_price_pair_output.xlsx" -f $inputStem)
$finalWorkbook = Join-Path $finalDir ("{0}_verified_price_anomaly_output.xlsx" -f $inputStem)

Write-Host "Stage 2A: running pairwise price-anomaly batches."
Invoke-ClaudeBatchStage -RunDir $stage2ARunDir -ParseScript $parseStage2A -MergeScript $mergeStage2A -OutputWorkbook $stage2AWorkbook

Write-Host "Stage 2B: preparing marketplace price-anomaly batches."
Invoke-PythonScript -Arguments @(
    $prepareStage2B,
    "--input-workbook", $stage2AWorkbook,
    "--output-root", $runRoot,
    "--batch-size", $BatchSize,
    "--run-id", "stage2b_marketplace"
)

$stage2BRunDir = Join-Path $runRoot "stage2b_marketplace"
Write-Host "Stage 2B: running marketplace price-anomaly batches."
Invoke-ClaudeBatchStage -RunDir $stage2BRunDir -ParseScript $parseStage2B -MergeScript $mergeStage2B -OutputWorkbook $finalWorkbook

$summary = [ordered]@{
    run_id = $runId
    completed_at = (Get-Date).ToString("s")
    input_workbook = [string]$inputWorkbookPath
    run_root = [string]$runRoot
    stage1_workbook = [string]$stage1Workbook
    stage2a_workbook = [string]$stage2AWorkbook
    stage2b_workbook = [string]$finalWorkbook
    final_workbook = [string]$finalWorkbook
}
$summaryPath = Join-Path $runRoot "run_summary.json"
$summary | ConvertTo-Json -Depth 4 | Set-Content -Path $summaryPath -Encoding UTF8

Write-Host "Full verification flow complete."
Write-Host "Final workbook: $finalWorkbook"
Write-Host "Run summary: $summaryPath"
