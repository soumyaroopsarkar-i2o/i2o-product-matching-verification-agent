import React, { useEffect, useRef, useState } from 'react';
import i2oLogo from './assets/i2o-logo.png';
import {
  agentMessages,
  backendBaseUrl,
  effortOptions,
  getVerificationJob,
  modelOptions,
  resultFilters,
  startVerification,
} from './services/verificationService';

const emptyMetrics = [
  { key: 'not_match', label: 'Not a Match', value: 0 },
  { key: 'exact', label: 'Exact Match', value: 0 },
  { key: 'equivalent', label: 'Equivalent Match', value: 0 },
];

function WorkingDots() {
  return (
    <span className="working-dots" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  );
}

function App() {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [runState, setRunState] = useState('idle');
  const [progress, setProgress] = useState(0);
  const [model, setModel] = useState('Sonnet 4.6');
  const [effort, setEffort] = useState('medium');
  const [activeResultFilter, setActiveResultFilter] = useState('all');
  const [liveResult, setLiveResult] = useState(null);
  const [jobId, setJobId] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  const isRunning = runState === 'running';
  const isDone = runState === 'done';
  const hasError = runState === 'error';
  const metrics = liveResult?.metrics || emptyMetrics;
  const previewSource = liveResult?.preview;
  const activePreviewRows = isDone ? previewSource?.[activeResultFilter]?.rows || [] : [];
  const totalBatches = liveResult?.totalBatches || 0;
  const completedBatches = liveResult?.completedBatches || 0;
  const activeBatch = liveResult?.currentBatch || 0;
  const activeMessage = hasError
    ? 'Verification needs attention'
    : isDone
    ? 'Output workbook is ready'
    : isRunning
      ? liveResult?.message || agentMessages[0]
      : file
        ? 'Ready to run verification'
        : 'Waiting for input file';
  const outputFileName = isDone && liveResult ? liveResult.outputFileName : 'Output workbook will appear after verification';
  const downloadHref = isDone && liveResult?.downloadUrl ? `${backendBaseUrl}${liveResult.downloadUrl}` : undefined;

  useEffect(() => {
    const restoredJobId = new URLSearchParams(window.location.search).get('jobId');
    if (!restoredJobId) return undefined;

    let cancelled = false;
    const restoreJob = async () => {
      try {
        const status = await getVerificationJob(restoredJobId);
        if (cancelled) return;

        setLiveResult(status);
        setJobId(restoredJobId);
        setProgress(status.progress || 0);
        if (status.state === 'done') {
          setRunState('done');
        } else if (status.state === 'error') {
          setErrorMessage(status.error || 'Verification failed.');
          setRunState('error');
        } else {
          setRunState('running');
        }
      } catch (error) {
        if (!cancelled) {
          setErrorMessage(error.message);
          setRunState('error');
        }
      }
    };

    restoreJob();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!jobId || !isRunning) return undefined;

    let cancelled = false;
    const poll = async () => {
      try {
        const status = await getVerificationJob(jobId);
        if (cancelled) return;

        setLiveResult(status);
        setProgress(status.progress || 0);

        if (status.state === 'done') {
          setRunState('done');
          return;
        }

        if (status.state === 'error') {
          setErrorMessage(status.error || 'Verification failed.');
          setRunState('error');
          return;
        }
      } catch (error) {
        if (!cancelled) {
          setErrorMessage(error.message);
          setRunState('error');
        }
      }
    };

    poll();
    const timer = window.setInterval(poll, 1200);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [jobId, isRunning]);

  function handleFileChange(event) {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) return;
    setFile(selectedFile);
    setProgress(0);
    setRunState('ready');
    setLiveResult(null);
    setJobId('');
    setErrorMessage('');
    setActiveResultFilter('all');
  }

  async function handleRun() {
    if (!file) {
      inputRef.current?.click();
      return;
    }

    setProgress(0);
    setRunState('running');
    setLiveResult(null);
    setJobId('');
    setErrorMessage('');

    try {
      const job = await startVerification({ file, model, effort });
      setLiveResult(job);
      setJobId(job.jobId);
      setProgress(job.progress || 0);
      window.history.replaceState(null, '', `?jobId=${encodeURIComponent(job.jobId)}`);
    } catch (error) {
      setErrorMessage(error.message);
      setRunState('error');
      setProgress(0);
    }
  }

  async function handleDownload(event) {
    if (!downloadHref || !isDone || !outputFileName) return;
    event.preventDefault();

    try {
      const response = await fetch(downloadHref);
      if (!response.ok) {
        throw new Error(`Download failed with status ${response.status}`);
      }

      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = outputFileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setErrorMessage(error.message || 'Download failed.');
      setRunState('error');
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <img src={i2oLogo} alt="i2o Inputs to Outputs" />
          <div>
            <strong>i2o Product Matching Verification Agent</strong>
          </div>
        </div>
      </header>

      <section className="agent-card">
        <div className="intro">
          <span>Verification Agent</span>
          <h1>Upload the input file. Let the agent work.</h1>
        </div>

        <div className="main-grid">
          <section className="upload-card">
            <button className={`file-picker ${file ? 'loaded' : ''}`} type="button" onClick={() => inputRef.current?.click()}>
              <span>XLSX</span>
              <div>
                <strong>{file?.name || 'Upload product verification input'}</strong>
                <small>{file ? 'Ready for live verification' : 'XLSX workbook only'}</small>
              </div>
            </button>
            <input ref={inputRef} type="file" accept=".xlsx" hidden onChange={handleFileChange} />

            <button className="run-button" type="button" onClick={handleRun} disabled={isRunning}>
              {isRunning ? 'Working...' : file ? 'Run verification' : 'Choose file'}
            </button>

            <div className="run-settings">
              <label>
                <span>Model</span>
                <select value={model} onChange={(event) => setModel(event.target.value)} disabled={isRunning}>
                  {modelOptions.map((option) => (
                    <option value={option} key={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Effort</span>
                <select value={effort} onChange={(event) => setEffort(event.target.value)} disabled={isRunning}>
                  {effortOptions.map((option) => (
                    <option value={option} key={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </section>

          <section className={`work-card ${runState}`}>
            <div className="work-head">
              <div>
                <span>{isDone ? 'Complete' : isRunning ? 'Agent working' : 'Status'}</span>
                <h2>
                  {activeMessage}
                  {isRunning && <WorkingDots />}
                </h2>
              </div>
              <strong>{progress}%</strong>
            </div>

            <div className="progress-track">
              <span style={{ width: `${progress}%` }} />
            </div>

            <div className="batch-line">
              <span>
                {hasError
                  ? 'Verification stopped'
                  : isRunning
                    ? 'Claude verification is running'
                    : isDone
                      ? 'Verified output is ready'
                      : 'Waiting for workbook'}
              </span>
              <span>
                {totalBatches
                  ? `Batch ${Math.min(activeBatch || totalBatches, totalBatches)} of ${totalBatches} (${completedBatches} complete)`
                  : isRunning
                    ? 'Preparing batches'
                    : isDone
                      ? 'Complete'
                      : hasError
                        ? 'Error'
                      : 'Idle'}
              </span>
            </div>

            <div className="run-config">
              <span>{model}</span>
              <span>Effort: {effort}</span>
            </div>

            {hasError && <p className="error-message">{errorMessage}</p>}

            <div className="batch-grid" aria-label="Batch progress">
              {Array.from({ length: totalBatches || 0 }, (_, index) => {
                const done = index + 1 <= completedBatches;
                const active = totalBatches && index + 1 === activeBatch && isRunning;
                return <span className={done ? 'done' : active ? 'active' : ''} key={index} />;
              })}
            </div>
          </section>
        </div>

        <section className="summary-card">
          <div>
            <span>Output</span>
            <strong>{outputFileName}</strong>
            <div className="download-row">
              <a
                className={!downloadHref ? 'download-link disabled' : 'download-link'}
                href={downloadHref}
                download={isDone ? outputFileName : undefined}
                onClick={handleDownload}
              >
                Download workbook
              </a>
            </div>
          </div>

          <div className="metric-strip">
            {metrics.map((metric) => (
              <article
                className={activeResultFilter === metric.key ? 'active' : ''}
                key={metric.label}
                onClick={() => setActiveResultFilter(metric.key)}
              >
                <span>{metric.label}</span>
                <strong>{metric.value}</strong>
              </article>
            ))}
          </div>
        </section>

        <section className={`results-preview ${isDone && liveResult ? 'visible' : ''}`}>
          <div className="preview-head">
            <div>
              <span>Results preview</span>
              <strong>{isDone && liveResult ? `${previewSource?.[activeResultFilter]?.label || 'Results'} preview` : 'Available after verification'}</strong>
            </div>
            <div className="filter-tabs">
              {resultFilters.map((filter) => (
                <button
                  className={activeResultFilter === filter.key ? 'active' : ''}
                  type="button"
                  onClick={() => setActiveResultFilter(filter.key)}
                  disabled={!isDone || !liveResult}
                  key={filter.key}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </div>

          {isDone && liveResult ? (
            <div className="preview-table-wrap">
              <table className="preview-table">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Source</th>
                    <th>Target</th>
                    <th>Status</th>
                    <th>Justification</th>
                  </tr>
                </thead>
                <tbody>
                  {activePreviewRows.map((row) => (
                    <tr key={`${activeResultFilter}-${row.row}`}>
                      <td>{row.row}</td>
                      <td>{row.sourceTitle}</td>
                      <td>{row.targetTitle}</td>
                      <td>{row.matchStatus}</td>
                      <td>{row.matchJustification || 'Blank for Exact'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!activePreviewRows.length && <p>No preview rows returned for this status. Download the workbook for the full output.</p>}
            </div>
          ) : (
            <p>Run the agent to show verified rows and download the output workbook.</p>
          )}
        </section>
      </section>
    </main>
  );
}

export default App;
