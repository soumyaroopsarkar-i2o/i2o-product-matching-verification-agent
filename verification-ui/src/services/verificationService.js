export const agentMessages = [
  'Reading input workbook',
  'Preparing source and target rows',
  'Verifying product matches',
  'Writing match justifications',
  'Caching batch results',
  'Preparing output workbook',
];

export const modelOptions = ['Opus 4.8', 'Opus 4.7', 'Sonnet 4.6'];

export const effortOptions = ['extra high', 'high', 'medium', 'low'];

export const resultFilters = [
  { key: 'all', label: 'All' },
  { key: 'not_match', label: 'Not a Match' },
  { key: 'exact', label: 'Exact Match' },
  { key: 'equivalent', label: 'Equivalent Match' },
];

export const backendBaseUrl = import.meta.env.VITE_VERIFICATION_API_URL || 'http://127.0.0.1:5175';

export async function startVerification({ file, model, effort }) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('model', model);
  formData.append('effort', effort);

  const response = await fetch(`${backendBaseUrl}/api/run-verification`, {
    method: 'POST',
    body: formData,
  });
  const payload = await response.json().catch(() => null);

  if (!response.ok || !payload?.ok) {
    const message = payload?.error || 'Verification backend failed.';
    const detail = payload?.details?.stderr || payload?.details?.message;
    throw new Error(detail ? `${message} ${detail}` : message);
  }

  return payload;
}

export async function getVerificationJob(jobId) {
  const response = await fetch(`${backendBaseUrl}/api/job/${encodeURIComponent(jobId)}`);
  const payload = await response.json().catch(() => null);

  if (!response.ok || !payload?.ok) {
    throw new Error(payload?.error || 'Unable to fetch verification job status.');
  }

  return payload;
}

export function estimateRows(file) {
  if (!file) return 0;
  return Math.max(80, Math.min(1200, Math.round(file.size / 4200)));
}

export function estimateBatches(rowCount) {
  if (!rowCount) return 0;
  return Math.max(1, Math.ceil(rowCount / 50));
}
