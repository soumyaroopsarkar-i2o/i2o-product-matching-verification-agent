import { createReadStream } from 'node:fs';
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');
const serverDataDir = path.join(__dirname, 'server-data');
const uploadDir = path.join(serverDataDir, 'uploads');
const runRoot = path.join(serverDataDir, 'runs');

const PORT = Number(process.env.VERIFICATION_API_PORT || 5175);
const pythonExe =
  process.env.PYTHON_EXE ||
  'C:\\Users\\SoumyaroopSarkar\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe';
const claudeExe = process.env.CLAUDE_EXE || 'claude';
const batchSize = Number(process.env.VERIFICATION_BATCH_SIZE || 40);
const claudeTimeoutMs = Number(process.env.CLAUDE_TIMEOUT_MS || 10 * 60 * 1000);
const jobs = new Map();

const modelMap = {
  'Opus 4.8': 'claude-opus-4-8',
  'Opus 4.7': 'claude-opus-4-7',
  'Sonnet 4.6': 'claude-sonnet-4-6',
};

const effortMap = {
  'extra high': 'extra-high',
  high: 'high',
  medium: 'medium',
  low: 'low',
};

function sendJson(response, statusCode, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  response.end(body);
}

function sendError(response, statusCode, message, details) {
  sendJson(response, statusCode, { ok: false, error: message, details });
}

function publicJob(job) {
  return {
    ok: true,
    jobId: job.jobId,
    state: job.state,
    phase: job.phase,
    message: job.message,
    progress: job.progress,
    totalBatches: job.totalBatches,
    completedBatches: job.completedBatches,
    currentBatch: job.currentBatch,
    outputFileName: job.outputFileName,
    downloadUrl: job.downloadUrl,
    total: job.total,
    metrics: job.metrics,
    preview: job.preview,
    error: job.error,
  };
}

function updateJob(jobId, patch) {
  const job = jobs.get(jobId);
  if (!job) return null;
  Object.assign(job, patch, { updatedAt: new Date().toISOString() });
  return job;
}

function sanitizeFileName(fileName) {
  const baseName = path.basename(fileName || 'verification_input.xlsx');
  return baseName.replace(/[^a-zA-Z0-9._-]/g, '_');
}

function makeRunId() {
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
  const suffix = Math.random().toString(36).slice(2, 8);
  return `ui_${stamp}_${suffix}`;
}

async function readRequestBody(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

function parseContentDisposition(header) {
  const result = {};
  for (const part of header.split(';')) {
    const [rawKey, ...rawValue] = part.trim().split('=');
    if (!rawValue.length) continue;
    result[rawKey] = rawValue.join('=').replace(/^"|"$/g, '');
  }
  return result;
}

function parseMultipart(body, contentType) {
  const boundaryMatch = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType || '');
  if (!boundaryMatch) {
    throw new Error('Missing multipart boundary.');
  }

  const boundary = Buffer.from(`--${boundaryMatch[1] || boundaryMatch[2]}`);
  const fields = {};
  const files = {};
  let cursor = 0;

  while (cursor < body.length) {
    const boundaryStart = body.indexOf(boundary, cursor);
    if (boundaryStart < 0) break;
    const partStart = boundaryStart + boundary.length;
    if (body.slice(partStart, partStart + 2).toString() === '--') break;

    const headersStart = body.slice(partStart, partStart + 2).toString() === '\r\n' ? partStart + 2 : partStart;
    const headersEnd = body.indexOf(Buffer.from('\r\n\r\n'), headersStart);
    if (headersEnd < 0) break;

    const nextBoundary = body.indexOf(boundary, headersEnd + 4);
    if (nextBoundary < 0) break;

    const headerText = body.slice(headersStart, headersEnd).toString('utf8');
    const contentEnd = body.slice(nextBoundary - 2, nextBoundary).toString() === '\r\n' ? nextBoundary - 2 : nextBoundary;
    const content = body.slice(headersEnd + 4, contentEnd);
    cursor = nextBoundary;

    const dispositionLine = headerText
      .split('\r\n')
      .find((line) => line.toLowerCase().startsWith('content-disposition:'));
    if (!dispositionLine) continue;

    const disposition = parseContentDisposition(dispositionLine.split(':').slice(1).join(':'));
    if (!disposition.name) continue;

    if (disposition.filename) {
      files[disposition.name] = {
        filename: disposition.filename,
        content,
      };
    } else {
      fields[disposition.name] = content.toString('utf8');
    }
  }

  return { fields, files };
}

function runProcess(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    let timedOut = false;
    const child = spawn(command, args, {
      cwd: options.cwd || repoRoot,
      env: { ...process.env, ...(options.env || {}) },
      shell: process.platform === 'win32' && !path.isAbsolute(command),
      windowsHide: true,
    });

    const stdout = [];
    const stderr = [];

    child.stdout.on('data', (chunk) => stdout.push(Buffer.from(chunk)));
    child.stderr.on('data', (chunk) => stderr.push(Buffer.from(chunk)));
    child.stdin.on('error', () => {
      // The command may exit before we finish writing a large prompt, for example
      // when the configured Claude executable is not available.
    });

    child.on('error', (error) => {
      if (timeout) clearTimeout(timeout);
      reject(error);
    });

    child.on('close', (code) => {
      if (timeout) clearTimeout(timeout);
      const result = {
        code,
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8'),
      };

      if (code === 0) {
        resolve(result);
      } else if (timedOut) {
        const error = new Error(`${command} timed out after ${Math.round(options.timeoutMs / 1000)} seconds`);
        error.result = result;
        reject(error);
      } else {
        const error = new Error(result.stderr || result.stdout || `${command} exited with code ${code}`);
        error.result = result;
        reject(error);
      }
    });

    const timeout = options.timeoutMs
      ? setTimeout(() => {
          timedOut = true;
          child.kill();
        }, options.timeoutMs)
      : null;

    if (options.input) {
      child.stdin.end(options.input);
    } else {
      child.stdin.end();
    }
  });
}

async function prepareRun(inputWorkbook, runId) {
  const prepareScript = path.join(repoRoot, 'scripts', 'prepare_claude_p_batches.py');
  await runProcess(pythonExe, [
    prepareScript,
    '--input-workbook',
    inputWorkbook,
    '--output-root',
    runRoot,
    '--run-id',
    runId,
    '--batch-size',
    String(batchSize),
  ]);
}

async function runClaudeBatches(runDir, model, effort, onProgress) {
  const parseScript = path.join(repoRoot, 'scripts', 'parse_claude_p_response.py');
  const manifestPath = path.join(runDir, 'manifest.json');
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  const cliModel = modelMap[model] || modelMap['Sonnet 4.6'];
  const cliEffort = effortMap[effort] || 'medium';
  let completed = 0;
  onProgress?.({
    totalBatches: manifest.batches.length,
    completedBatches: completed,
    currentBatch: manifest.batches.length ? 1 : 0,
  });

  for (const batch of manifest.batches) {
    const resultPath = String(batch.result_path);
    try {
      await stat(resultPath);
      completed += 1;
      onProgress?.({
        completedBatches: completed,
        currentBatch: Math.min(completed + 1, manifest.batches.length),
      });
      continue;
    } catch {
      // Cache miss: run this batch.
    }

    onProgress?.({
      currentBatch: batch.batch_index + 1,
      message: `Verifying batch ${batch.batch_index + 1} of ${manifest.batches.length}`,
    });

    const instruction = await readFile(String(batch.instruction_path), 'utf8');
    const raw = await runProcess(claudeExe, ['-p', '--model', cliModel, '--effort', cliEffort], {
      input: instruction,
      timeoutMs: claudeTimeoutMs,
    });

    await mkdir(path.dirname(String(batch.raw_response_path)), { recursive: true });
    await writeFile(String(batch.raw_response_path), raw.stdout, 'utf8');

    await runProcess(pythonExe, [parseScript, '--run-dir', runDir, '--batch', String(batch.batch_index)]);
    completed += 1;
    onProgress?.({
      completedBatches: completed,
      currentBatch: Math.min(completed + 1, manifest.batches.length),
      message: `Cached batch ${completed} of ${manifest.batches.length}`,
    });
  }
}

async function mergeRun(runDir) {
  const mergeScript = path.join(repoRoot, 'scripts', 'merge_claude_p_results.py');
  await runProcess(pythonExe, [mergeScript, '--run-dir', runDir]);
}

async function preparePricePairRun(inputWorkbook, outputRoot, runId) {
  const prepareScript = path.join(repoRoot, 'scripts', 'prepare_price_pair_batches.py');
  await runProcess(pythonExe, [
    prepareScript,
    '--input-workbook',
    inputWorkbook,
    '--output-root',
    outputRoot,
    '--run-id',
    runId,
    '--batch-size',
    String(batchSize),
  ]);
}

async function prepareMarketplaceOutlierRun(inputWorkbook, outputRoot, runId) {
  const prepareScript = path.join(repoRoot, 'scripts', 'prepare_marketplace_outlier_batches.py');
  await runProcess(pythonExe, [
    prepareScript,
    '--input-workbook',
    inputWorkbook,
    '--output-root',
    outputRoot,
    '--run-id',
    runId,
    '--batch-size',
    String(batchSize),
  ]);
}

async function runAgentBatches(runDir, parseScript, model, effort, onProgress) {
  const manifestPath = path.join(runDir, 'manifest.json');
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  const cliModel = modelMap[model] || modelMap['Sonnet 4.6'];
  const cliEffort = effortMap[effort] || 'medium';
  let completed = 0;
  onProgress?.({
    totalBatches: manifest.batches.length,
    completedBatches: completed,
    currentBatch: manifest.batches.length ? 1 : 0,
  });

  for (const batch of manifest.batches) {
    const resultPath = String(batch.result_path);
    try {
      await stat(resultPath);
      completed += 1;
      onProgress?.({
        completedBatches: completed,
        currentBatch: Math.min(completed + 1, manifest.batches.length),
      });
      continue;
    } catch {
      // Cache miss: run this batch.
    }

    onProgress?.({
      currentBatch: batch.batch_index + 1,
      message: `Verifying batch ${batch.batch_index + 1} of ${manifest.batches.length}`,
    });

    const instruction = await readFile(String(batch.instruction_path), 'utf8');
    const raw = await runProcess(claudeExe, ['-p', '--model', cliModel, '--effort', cliEffort], {
      input: instruction,
      timeoutMs: claudeTimeoutMs,
    });

    await mkdir(path.dirname(String(batch.raw_response_path)), { recursive: true });
    await writeFile(String(batch.raw_response_path), raw.stdout, 'utf8');

    await runProcess(pythonExe, [parseScript, '--run-dir', runDir, '--batch', String(batch.batch_index)]);
    completed += 1;
    onProgress?.({
      completedBatches: completed,
      currentBatch: Math.min(completed + 1, manifest.batches.length),
      message: `Cached batch ${completed} of ${manifest.batches.length}`,
    });
  }
}

async function mergePricePairRun(runDir, outputWorkbook) {
  const mergeScript = path.join(repoRoot, 'scripts', 'merge_price_pair_results.py');
  await runProcess(pythonExe, [mergeScript, '--run-dir', runDir, '--output-workbook', outputWorkbook]);
}

async function mergeMarketplaceOutlierRun(runDir, outputWorkbook) {
  const mergeScript = path.join(repoRoot, 'scripts', 'merge_marketplace_outlier_results.py');
  await runProcess(pythonExe, [mergeScript, '--run-dir', runDir, '--output-workbook', outputWorkbook]);
}

async function summarizeRun(runDir) {
  const summaryPath = path.join(runDir, 'run_summary.json');
  const runSummary = JSON.parse(await readFile(summaryPath, 'utf8'));
  const outputWorkbook = String(runSummary.final_workbook);
  const summarizeScript = path.join(__dirname, 'scripts', 'summarize_output.py');
  const summaryResult = await runProcess(pythonExe, [summarizeScript, '--workbook', outputWorkbook]);
  return {
    outputWorkbook,
    summary: JSON.parse(summaryResult.stdout),
  };
}

async function executeVerificationJob(jobId) {
  const job = jobs.get(jobId);
  if (!job) return;

  try {
    updateJob(jobId, {
      state: 'running',
      phase: 'preparing',
      message: 'Preparing verification batches',
      progress: 3,
    });

    await prepareRun(job.uploadedWorkbook, job.runId);
    const runDir = path.join(runRoot, job.runId);
    const finalDir = path.join(runDir, 'final');
    await mkdir(finalDir, { recursive: true });
    const manifest = JSON.parse(await readFile(path.join(runDir, 'manifest.json'), 'utf8'));

    updateJob(jobId, {
      phase: 'stage1',
      message: `Starting ${manifest.batches.length} Claude batch${manifest.batches.length === 1 ? '' : 'es'}`,
      totalBatches: manifest.batches.length,
      completedBatches: 0,
      currentBatch: manifest.batches.length ? 1 : 0,
      progress: 8,
    });

    await runClaudeBatches(runDir, job.model, job.effort, (progressPatch) => {
      const total = progressPatch.totalBatches ?? jobs.get(jobId)?.totalBatches ?? 0;
      const completed = progressPatch.completedBatches ?? jobs.get(jobId)?.completedBatches ?? 0;
      const progress = total ? Math.min(45, Math.round(8 + (completed / total) * 37)) : 8;
      updateJob(jobId, {
        phase: 'stage1',
        progress,
        ...progressPatch,
      });
    });

    updateJob(jobId, {
      phase: 'merging',
      message: 'Writing verified output workbook',
      progress: 95,
    });

    await mergeRun(runDir);

    const stage1Manifest = JSON.parse(await readFile(path.join(runDir, 'manifest.json'), 'utf8'));
    const stage1Workbook = String(stage1Manifest.output_workbook);

    updateJob(jobId, {
      phase: 'stage2a_preparing',
      message: 'Preparing pairwise price anomaly batches',
      progress: 48,
      completedBatches: 0,
      currentBatch: 0,
    });

    const stage2ARunId = 'stage2a_pair';
    const stage2ARunDir = path.join(runDir, stage2ARunId);
    await preparePricePairRun(stage1Workbook, runDir, stage2ARunId);

    const stage2AManifest = JSON.parse(await readFile(path.join(stage2ARunDir, 'manifest.json'), 'utf8'));
    updateJob(jobId, {
      phase: 'stage2a',
      message: `Starting ${stage2AManifest.batches.length} pairwise price batch${stage2AManifest.batches.length === 1 ? '' : 'es'}`,
      totalBatches: stage2AManifest.batches.length,
      completedBatches: 0,
      currentBatch: stage2AManifest.batches.length ? 1 : 0,
      progress: 50,
    });

    await runAgentBatches(stage2ARunDir, path.join(repoRoot, 'scripts', 'parse_price_pair_response.py'), job.model, job.effort, (progressPatch) => {
      const total = progressPatch.totalBatches ?? jobs.get(jobId)?.totalBatches ?? 0;
      const completed = progressPatch.completedBatches ?? jobs.get(jobId)?.completedBatches ?? 0;
      const progress = total ? Math.min(70, Math.round(50 + (completed / total) * 20)) : 50;
      updateJob(jobId, {
        phase: 'stage2a',
        progress,
        ...progressPatch,
      });
    });

    const inputStem = path.basename(job.uploadedWorkbook, path.extname(job.uploadedWorkbook));
    const stage2AWorkbook = path.join(finalDir, `${inputStem}_stage2a_price_pair_output.xlsx`);
    await mergePricePairRun(stage2ARunDir, stage2AWorkbook);

    updateJob(jobId, {
      phase: 'stage2b_preparing',
      message: 'Preparing marketplace anomaly batches',
      progress: 74,
      completedBatches: 0,
      currentBatch: 0,
    });

    const stage2BRunId = 'stage2b_marketplace';
    const stage2BRunDir = path.join(runDir, stage2BRunId);
    await prepareMarketplaceOutlierRun(stage2AWorkbook, runDir, stage2BRunId);

    const stage2BManifest = JSON.parse(await readFile(path.join(stage2BRunDir, 'manifest.json'), 'utf8'));
    updateJob(jobId, {
      phase: 'stage2b',
      message: `Starting ${stage2BManifest.batches.length} marketplace anomaly batch${stage2BManifest.batches.length === 1 ? '' : 'es'}`,
      totalBatches: stage2BManifest.batches.length,
      completedBatches: 0,
      currentBatch: stage2BManifest.batches.length ? 1 : 0,
      progress: 76,
    });

    await runAgentBatches(stage2BRunDir, path.join(repoRoot, 'scripts', 'parse_marketplace_outlier_response.py'), job.model, job.effort, (progressPatch) => {
      const total = progressPatch.totalBatches ?? jobs.get(jobId)?.totalBatches ?? 0;
      const completed = progressPatch.completedBatches ?? jobs.get(jobId)?.completedBatches ?? 0;
      const progress = total ? Math.min(92, Math.round(76 + (completed / total) * 16)) : 92;
      updateJob(jobId, {
        phase: 'stage2b',
        progress,
        ...progressPatch,
      });
    });

    updateJob(jobId, {
      phase: 'merging',
      message: 'Writing verified output workbook',
      progress: 95,
    });

    const finalWorkbook = path.join(finalDir, `${inputStem}_verified_price_anomaly_output.xlsx`);
    await mergeMarketplaceOutlierRun(stage2BRunDir, finalWorkbook);

    const runSummary = {
      run_id: job.runId,
      completed_at: new Date().toISOString(),
      input_workbook: job.uploadedWorkbook,
      run_root: runDir,
      stage1_workbook: stage1Workbook,
      stage2a_workbook: stage2AWorkbook,
      stage2b_workbook: finalWorkbook,
      final_workbook: finalWorkbook,
    };
    await writeFile(path.join(runDir, 'run_summary.json'), JSON.stringify(runSummary, null, 2), 'utf8');

    const { outputWorkbook, summary } = await summarizeRun(runDir);
    const outputFileName = path.basename(outputWorkbook);

    updateJob(jobId, {
      state: 'done',
      phase: 'complete',
      message: 'Verified output workbook is ready',
      progress: 100,
      outputFileName,
      downloadUrl: `/api/output/${encodeURIComponent(job.runId)}/${encodeURIComponent(outputFileName)}`,
      ...summary,
    });
  } catch (error) {
    const missingClaude = error.code === 'ENOENT' || /not recognized|not found|ENOENT/i.test(error.message);
    updateJob(jobId, {
      state: 'error',
      phase: 'error',
      progress: 0,
      message: 'Verification failed',
      error: missingClaude
        ? `Claude command was not found by the backend. Set CLAUDE_EXE to the full claude executable path. Current value: ${claudeExe}`
        : error.message,
      details: {
        message: error.message,
        stdout: error.result?.stdout,
        stderr: error.result?.stderr,
      },
    });
  }
}

async function handleRunVerification(request, response) {
  const body = await readRequestBody(request);
  const { fields, files } = parseMultipart(body, request.headers['content-type']);
  const uploadedFile = files.file;

  if (!uploadedFile) {
    sendError(response, 400, 'Upload a product verification workbook first.');
    return;
  }

  const originalName = sanitizeFileName(uploadedFile.filename);
  if (!/\.xlsx$/i.test(originalName)) {
    sendError(response, 400, 'Live verification currently expects an .xlsx workbook.');
    return;
  }

  const runId = makeRunId();
  const jobId = runId;
  const uploadedWorkbook = path.join(uploadDir, `${runId}_${originalName}`);

  await mkdir(uploadDir, { recursive: true });
  await mkdir(runRoot, { recursive: true });
  await writeFile(uploadedWorkbook, uploadedFile.content);

  const job = {
    jobId,
    runId,
    state: 'queued',
    phase: 'queued',
    message: 'Queued verification job',
    progress: 0,
    totalBatches: 0,
    completedBatches: 0,
    currentBatch: 0,
    uploadedWorkbook,
    model: fields.model,
    effort: fields.effort,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  jobs.set(jobId, job);

  setImmediate(() => {
    executeVerificationJob(jobId);
  });

  sendJson(response, 202, publicJob(job));
}

async function handleDownload(request, response, url) {
  const [, apiSegment, outputSegment, runId, fileName] = url.pathname.split('/');
  if (apiSegment !== 'api' || outputSegment !== 'output') {
    sendError(response, 404, 'Output route was not found.');
    return;
  }
  const safeRunId = decodeURIComponent(runId || '').replace(/[^a-zA-Z0-9_-]/g, '');
  const safeFileName = sanitizeFileName(decodeURIComponent(fileName || ''));
  const filePath = path.join(runRoot, safeRunId, 'final', safeFileName);

  try {
    const fileInfo = await stat(filePath);
    response.writeHead(200, {
      'Access-Control-Allow-Origin': '*',
      'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'Content-Length': fileInfo.size,
      'Content-Disposition': `attachment; filename="${safeFileName}"`,
    });
    createReadStream(filePath).pipe(response);
  } catch {
    sendError(response, 404, 'Output file was not found.');
  }
}

async function route(request, response) {
  const url = new URL(request.url, `http://${request.headers.host}`);

  if (request.method === 'OPTIONS') {
    response.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    response.end();
    return;
  }

  try {
    if (request.method === 'GET' && url.pathname === '/api/health') {
      sendJson(response, 200, {
        ok: true,
        claudeExe,
        pythonExe,
        batchSize,
        claudeTimeoutMs,
      });
      return;
    }

    if (request.method === 'POST' && url.pathname === '/api/run-verification') {
      await handleRunVerification(request, response);
      return;
    }

    if (request.method === 'GET' && url.pathname.startsWith('/api/job/')) {
      const jobId = decodeURIComponent(url.pathname.split('/')[3] || '');
      const job = jobs.get(jobId);
      if (!job) {
        sendError(response, 404, 'Verification job was not found.');
        return;
      }
      sendJson(response, 200, publicJob(job));
      return;
    }

    if (request.method === 'GET' && url.pathname.startsWith('/api/output/')) {
      await handleDownload(request, response, url);
      return;
    }

    sendError(response, 404, 'Route not found.');
  } catch (error) {
    sendError(response, 500, 'Backend request failed.', { message: error.message });
  }
}

http.createServer(route).listen(PORT, '127.0.0.1', () => {
  console.log(`Verification backend listening on http://127.0.0.1:${PORT}`);
  console.log(`Claude executable: ${claudeExe}`);
});
