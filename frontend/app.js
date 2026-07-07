/**
 * Product Discovery Team — Frontend Logic
 *
 * Implements:
 *  - Card expand/collapse (Frontend-Spec §1)
 *  - Composition rules enforcement (Frontend-Spec §1)
 *  - Client-side Tier 1 validation (Frontend-Spec §3)
 *  - File upload with drag & drop (Frontend-Spec §4)
 *  - Form submission → POST /submit
 *  - Status polling → GET /status/{request_id} (Frontend-Spec §3 + resolved decision)
 *  - Clarification loop rendering (Frontend-Spec §5)
 *  - Results view (Frontend-Spec §7)
 *  - Retry → POST /retry (Frontend-Spec §6)
 */

const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100 MB
const ACCEPTED_TYPES = new Set(['.mp3', '.wav', '.m4a', '.txt', '.md']);
const POLL_INTERVAL_MS = 2500;

// ── DOM Refs ────────────────────────────────────────────────────────
const form = document.getElementById('discovery-form');
const submitBtn = document.getElementById('submit-btn');
const submitHint = document.getElementById('submit-hint');
const btnText = submitBtn.querySelector('.btn-text');
const btnSpinner = submitBtn.querySelector('.btn-spinner');

// Card A
const wantReport = document.getElementById('want_report');
const cardA = document.getElementById('card-a');
const cardABody = document.getElementById('card-a-body');
const topicInput = document.getElementById('topic');
const topicError = document.getElementById('topic-error');

// Card B
const wantTranscript = document.getElementById('want_transcript');
const cardB = document.getElementById('card-b');
const cardBBody = document.getElementById('card-b-body');
const fileInput = document.getElementById('transcript_file');
const uploadZone = document.getElementById('upload-zone');
const uploadContent = document.getElementById('upload-content');
const uploadFile = document.getElementById('upload-file');
const fileName = document.getElementById('file-name');
const fileSize = document.getElementById('file-size');
const fileRemove = document.getElementById('file-remove');
const uploadBtn = document.getElementById('upload-btn');
const fileError = document.getElementById('file-error');
const purposeInput = document.getElementById('interview_purpose');
const purposeError = document.getElementById('purpose-error');
const contextInput = document.getElementById('interview_background');
const contextError = document.getElementById('context-error');

// Card C
const wantRecommendation = document.getElementById('want_recommendation');
const cardC = document.getElementById('card-c');
const recHint = document.getElementById('rec-hint');

// Results
const bannerArea = document.getElementById('banner-area');
const clarificationArea = document.getElementById('clarification-area');
const resultsView = document.getElementById('results-view');
const resultsCards = document.getElementById('results-cards');

// ── State ───────────────────────────────────────────────────────────
let currentRequestId = null;
let pollTimer = null;

// ── Composition Rules ───────────────────────────────────────────────
function updateComposition() {
  const hasAorB = wantReport.checked || wantTranscript.checked;

  // Card A expand/collapse
  cardABody.hidden = !wantReport.checked;
  cardA.classList.toggle('active', wantReport.checked);

  // Card B expand/collapse
  cardBBody.hidden = !wantTranscript.checked;
  cardB.classList.toggle('active', wantTranscript.checked);

  // Card C: disabled unless A or B checked
  wantRecommendation.disabled = !hasAorB;
  cardC.classList.toggle('enabled', hasAorB);
  if (!hasAorB) {
    wantRecommendation.checked = false;
    recHint.textContent = 'Requires Report or Transcript';
  } else {
    recHint.textContent = 'Synthesize a strategic brief from your results';
  }

  // Submit button state
  submitBtn.disabled = !hasAorB;
  submitHint.textContent = hasAorB ? '' : 'Select Report or Transcript to continue.';

  clearAllErrors();
}

wantReport.addEventListener('change', updateComposition);
wantTranscript.addEventListener('change', updateComposition);

// ── File Upload ─────────────────────────────────────────────────────
uploadBtn.addEventListener('click', (e) => {
  e.preventDefault();
  fileInput.click();
});

uploadZone.addEventListener('click', (e) => {
  if (e.target !== fileRemove && !e.target.closest('.file-remove')) {
    fileInput.click();
  }
});

fileInput.addEventListener('change', () => {
  if (fileInput.files.length) handleFile(fileInput.files[0]);
});

// Drag & drop
uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadZone.classList.add('dragover');
});
uploadZone.addEventListener('dragleave', () => {
  uploadZone.classList.remove('dragover');
});
uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) {
    handleFile(e.dataTransfer.files[0]);
  }
});

function handleFile(file) {
  hideError(fileError);

  const ext = '.' + file.name.split('.').pop().toLowerCase();
  if (!ACCEPTED_TYPES.has(ext)) {
    showError(fileError, "Unsupported file type. Upload an audio file (.mp3, .wav, .m4a) or a text file (.txt).");
    return;
  }

  if (file.size > MAX_FILE_SIZE) {
    showError(fileError, "File is too large (max 100 MB).");
    return;
  }

  if (file.size === 0) {
    showError(fileError, "This file appears to be empty or unreadable — try uploading again.");
    return;
  }

  // Show file info
  const dt = new DataTransfer();
  dt.items.add(file);
  fileInput.files = dt.files;

  fileName.textContent = file.name;
  fileSize.textContent = formatFileSize(file.size);
  uploadContent.hidden = true;
  uploadFile.hidden = false;
}

fileRemove.addEventListener('click', (e) => {
  e.stopPropagation();
  fileInput.value = '';
  uploadContent.hidden = false;
  uploadFile.hidden = true;
});

function formatFileSize(bytes) {
  if (bytes < 1000) return bytes + ' B';
  if (bytes < 1000 * 1000) return (bytes / 1000).toFixed(1) + ' KB';
  return (bytes / (1000 * 1000)).toFixed(1) + ' MB';
}

// ── Validation ──────────────────────────────────────────────────────
function showError(el, msg) {
  el.textContent = msg;
  el.hidden = false;
}

function hideError(el) {
  el.hidden = true;
  el.textContent = '';
}

function clearAllErrors() {
  [topicError, fileError, purposeError, contextError].forEach(hideError);
}

function validateTier1() {
  let valid = true;
  clearAllErrors();

  if (wantReport.checked && !topicInput.value.trim()) {
    showError(topicError, "Add a topic to research.");
    valid = false;
  }

  if (wantTranscript.checked) {
    if (!fileInput.files.length) {
      showError(fileError, "Upload an audio or text file.");
      valid = false;
    }
    if (!purposeInput.value.trim()) {
      showError(purposeError, "Tell us the interview's purpose — this helps format it well.");
      valid = false;
    }
    if (!contextInput.value.trim()) {
      showError(contextError, "Add some background context (company, product, etc.).");
      valid = false;
    }
  }

  return valid;
}

// ── Form Submit ─────────────────────────────────────────────────────
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!validateTier1()) return;

  setSubmitting(true);

  const formData = new FormData();
  formData.append('want_report', wantReport.checked);
  formData.append('topic', topicInput.value);
  formData.append('want_transcript', wantTranscript.checked);
  if (wantTranscript.checked && fileInput.files.length) {
    formData.append('transcript_file', fileInput.files[0]);
  }
  formData.append('interview_purpose', purposeInput.value);
  formData.append('interview_background', contextInput.value);
  formData.append('participant_count', document.getElementById('participant_count').value || '');
  formData.append('want_mindmap', document.getElementById('want_mindmap').checked);
  formData.append('want_recommendation', wantRecommendation.checked);

  try {
    const res = await fetch('/submit', { method: 'POST', body: formData });
    const data = await res.json();

    if (!res.ok) {
      showBanner('error', data.errors ? data.errors.join(' ') : 'Submission failed.');
      setSubmitting(false);
      return;
    }

    currentRequestId = data.request_id;
    showBanner('info', `Request accepted — tracking ID: ${currentRequestId}`);
    showResultsView(data);
    startPolling();
  } catch (err) {
    showBanner('error', 'Something unexpected happened. Please try again or start a new request.');
  }

  setSubmitting(false);
});

function setSubmitting(loading) {
  submitBtn.disabled = loading;
  btnText.textContent = loading ? 'Submitting…' : 'Submit Request';
  btnSpinner.hidden = !loading;
}

// ── Banners ─────────────────────────────────────────────────────────
function showBanner(type, message) {
  bannerArea.hidden = false;
  bannerArea.innerHTML = `<div class="banner banner-${type}">${escapeHtml(message)}</div>`;

  // Auto-hide info banners after 8 seconds
  if (type === 'info') {
    setTimeout(() => { bannerArea.hidden = true; }, 8000);
  }
}

function hideBanner() {
  bannerArea.hidden = true;
  bannerArea.innerHTML = '';
}

// ── Results View ────────────────────────────────────────────────────
const ARTIFACT_META = {
  report:         { name: 'Research Report',     icon: '📊' },
  transcript:     { name: 'Interview Transcript', icon: '🎙' },
  summary:        { name: 'Interview Summary',    icon: '📝' },
  recommendation: { name: 'Recommendation Brief', icon: '💡' },
};

// Download filename overrides (key → filename without extension)
const DOWNLOAD_FILENAMES = {
  report:         'research-report',
  transcript:     'transcript',
  summary:        'interview-summary',
  recommendation: 'recommendation-brief',
};

// Display order
const ARTIFACT_ORDER = ['report', 'transcript', 'summary', 'recommendation'];

function showResultsView(data) {
  resultsView.hidden = false;
  renderResults(data.artifacts || {}, data.outputs || {});
}

function renderResults(artifacts, outputs) {
  resultsCards.innerHTML = '';

  // Render in defined order, then any unexpected extras
  const orderedKeys = [
    ...ARTIFACT_ORDER.filter(k => k in artifacts),
    ...Object.keys(artifacts).filter(k => !ARTIFACT_ORDER.includes(k)),
  ];

  for (const key of orderedKeys) {
    const status = artifacts[key];
    if (status === null || status === undefined) continue;

    const meta = ARTIFACT_META[key] || { name: key, icon: '📦' };
    const card = document.createElement('div');
    card.className = 'result-card';

    let iconClass = 'generating';
    let statusText = 'Generating…';
    let actionHtml = '';

    if (status === 'ready') {
      iconClass = 'ready';
      statusText = 'Ready';

      const output = outputs[key];
      if (key === 'mindmap' && output && output.startsWith('http')) {
        actionHtml = `<a href="${escapeHtml(output)}" target="_blank" rel="noopener" class="result-action link">Open in Miro</a>`;
      } else if (output) {
        actionHtml = `<button class="result-action download" data-artifact="${key}">Download</button>`;
      }
    } else if (status === 'failed') {
      iconClass = 'failed';
      statusText = 'Failed';
      actionHtml = `<button class="result-action retry" data-artifact="${key}">Retry</button>`;
    }

    card.innerHTML = `
      <div class="result-card-header">
        <div class="result-icon ${iconClass}">${meta.icon}</div>
        <div class="result-info">
          <div class="result-name">${meta.name}</div>
          <div class="result-status ${iconClass}">${statusText}</div>
        </div>
        ${actionHtml}
      </div>
    `;

    resultsCards.appendChild(card);
  }

  // Bind download/retry buttons
  resultsCards.querySelectorAll('.download').forEach(btn => {
    btn.addEventListener('click', () => downloadArtifact(btn.dataset.artifact, outputs));
  });
  resultsCards.querySelectorAll('.retry').forEach(btn => {
    btn.addEventListener('click', () => retryArtifact(btn.dataset.artifact));
  });
}

// ── Download ────────────────────────────────────────────────────────
function downloadArtifact(artifactKey, outputs) {
  const content = outputs[artifactKey];
  if (!content) return;

  const text = typeof content === 'object' ? JSON.stringify(content, null, 2) : content;
  const filename = (DOWNLOAD_FILENAMES[artifactKey] || artifactKey) + '.md';
  const blob = new Blob([text], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Retry ───────────────────────────────────────────────────────────
async function retryArtifact(artifactKey) {
  if (!currentRequestId) return;

  try {
    const res = await fetch('/retry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: currentRequestId,
        artifact: artifactKey,
      }),
    });
    const data = await res.json();
    if (res.ok) {
      renderResults(data.artifacts, data.outputs);
      showBanner('info', `Retrying ${ARTIFACT_META[artifactKey]?.name || artifactKey}…`);
    } else {
      showBanner('error', data.error || 'Retry failed.');
    }
  } catch {
    showBanner('error', 'Something went wrong. Please try again.');
  }
}

// ── Polling ─────────────────────────────────────────────────────────
function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollStatus, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollStatus() {
  if (!currentRequestId) return;

  try {
    const res = await fetch(`/status/${currentRequestId}`);
    if (!res.ok) return;
    const data = await res.json();
    renderResults(data.artifacts || {}, data.outputs || {});

    // Stop polling when all artifacts are in a terminal state
    const statuses = Object.values(data.artifacts || {}).filter(s => s !== null);
    const allDone = statuses.every(s => s === 'ready' || s === 'failed');
    if (allDone && statuses.length > 0) {
      stopPolling();
    }
  } catch {
    // Silently retry on next interval
  }
}

// ── Clarification (HITL) ────────────────────────────────────────────
function showClarification(questions) {
  clarificationArea.hidden = false;
  clarificationArea.innerHTML = `
    <h3 class="clarification-title">A couple more details will help</h3>
    ${questions.map((q, i) => `
      <div class="clarify-field">
        <p class="clarify-question">${escapeHtml(q.question)}</p>
        <input type="text" class="clarify-input" data-field="${escapeHtml(q.field)}" id="clarify-${i}">
      </div>
    `).join('')}
    <button class="clarify-submit" id="clarify-submit-btn">Continue</button>
  `;

  document.getElementById('clarify-submit-btn').addEventListener('click', submitClarification);
}

async function submitClarification() {
  // This would submit clarification answers back to the backend
  // For the polling-based prototype, this is handled via the Workflow HITL mechanism
  clarificationArea.hidden = true;
}

// ── Utilities ───────────────────────────────────────────────────────
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Initialize
updateComposition();
