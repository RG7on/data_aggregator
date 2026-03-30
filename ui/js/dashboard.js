// ══════════════════════════════════════════════════════════════════════════
//  dashboard.js — Dashboard stats, scrape log, manual scrape trigger, init
// ══════════════════════════════════════════════════════════════════════════

// ── updateDashboard ───────────────────────────────────────────────────────
function updateDashboard(statusData) {
  document.getElementById('stat-total-reports').textContent = cuicReports.length + smaxReports.length;
  if (!statusData?.length) {
    document.getElementById('stat-last-run').textContent    = 'Never';
    document.getElementById('stat-success-rate').textContent = '-';
    document.getElementById('stat-total-rows').textContent  = '0';
    return;
  }
  document.getElementById('stat-last-run').textContent = statusData[0].timestamp || '-';
  const ok = statusData.filter(s => s.status === 'success').length;
  document.getElementById('stat-success-rate').textContent = Math.round(ok / statusData.length * 100) + '%';
  document.getElementById('stat-total-rows').textContent   = statusData.reduce((s, r) => s + (r.row_count || 0), 0).toLocaleString();
}

// ── renderScrapeLog ───────────────────────────────────────────────────────
function renderScrapeLog(log) {
  const tb = document.getElementById('scrape-log-body');
  if (!tb) return;
  if (!log?.length) {
    tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:20px">No scrape history yet.</td></tr>';
    return;
  }
  tb.innerHTML = log.map(r => `<tr>
    <td>${esc(r.timestamp)}</td>
    <td>${esc(r.source)}</td>
    <td>${esc(r.report_label)}</td>
    <td><span class="status-pill ${r.status}">${esc(r.status)}</span></td>
    <td>${r.row_count || 0}</td>
    <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${attr(r.message)}">${esc(r.message || '')}</td>
  </tr>`).join('');
}

// ── renderAgentInsights ───────────────────────────────────────────────────
function renderAgentInsights(payload) {
  const body = document.getElementById('agent-insights-body');
  const summary = document.getElementById('agent-insights-summary');
  if (!body || !summary) return;

  if (!payload || !Array.isArray(payload.insights)) {
    summary.textContent = 'Unavailable';
    body.innerHTML = '<div class="agent-empty">AI insights are currently unavailable.</div>';
    return;
  }

  const s = payload.summary || {};
  const total = payload.insights.length;
  summary.textContent = `${s.high || 0} high · ${s.medium || 0} medium · ${s.low || 0} low`;

  if (total === 0) {
    body.innerHTML = '<div class="agent-empty">No active issues detected from recent scrape history.</div>';
    return;
  }

  body.innerHTML = payload.insights.slice(0, 6).map(i => {
    const sev = esc(i.severity || 'low');
    const conf = Math.round((i.confidence || 0) * 100);
    const title = esc((i.source || '?') + ' / ' + (i.report_label || '?'));
    const why = esc(i.why || 'No explanation provided.');
    const actions = (i.recommended_actions || []).slice(0, 2)
      .map(a => `<li>${esc(a)}</li>`).join('');
    return `<div class="agent-item severity-${sev}">
      <div class="agent-item-head">
        <div class="agent-item-title">${title}</div>
        <div class="agent-meta">
          <span class="agent-severity ${sev}">${sev.toUpperCase()}</span>
          <span class="agent-confidence">${conf}%</span>
        </div>
      </div>
      <div class="agent-item-why">${why}</div>
      <ul class="agent-actions">${actions}</ul>
    </div>`;
  }).join('');
}

// ── startManualScrape ─────────────────────────────────────────────────────
async function startManualScrape() {
  const btn      = document.getElementById('manual-scrape-btn');
  const statusEl = document.getElementById('manual-scrape-status');
  if (btn.disabled) return;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Starting\u2026';
  statusEl.textContent = 'Saving settings\u2026';
  statusEl.style.color = 'var(--accent)';

  try {
    const saved = await saveAll(true);
    if (!saved) {
      btn.disabled = false;
      btn.innerHTML = _scrapeRunBtnHtml;
      statusEl.textContent = 'Save failed. Fix errors and try again.';
      statusEl.style.color = 'var(--red)';
      return;
    }

    statusEl.textContent = 'Starting scrape\u2026';
    const res  = await fetch('/api/run-scrape', { method: 'POST' });
    const data = await res.json();

    if (res.ok) {
      btn.innerHTML = '<span class="spinner"></span> Running\u2026';
      statusEl.textContent = 'Scrape running in the background\u2026';
      statusEl.style.color = 'var(--green)';
      showToast('Scrape started!', 'success');

      const pollInterval = setInterval(async () => {
        try {
          const checkRes  = await fetch('/api/scrape-running');
          const checkData = await checkRes.json();
          if (!checkData.running) {
            clearInterval(pollInterval);
            btn.disabled = false;
            btn.innerHTML = _scrapeRunBtnHtml;
            statusEl.textContent = 'Scrape complete! Refreshing\u2026';
            statusEl.style.color = 'var(--green)';
            await loadFromServer();
            setTimeout(() => { statusEl.textContent = ''; }, 5000);
          }
        } catch(e) { /* keep polling */ }
      }, 3000);

    } else {
      btn.disabled = false;
      btn.innerHTML = _scrapeRunBtnHtml;
      statusEl.textContent = data.error || 'Failed to start scrape';
      statusEl.style.color = 'var(--red)';
      showToast(data.error || 'Failed to start scrape', 'error');
    }
  } catch(e) {
    btn.disabled = false;
    btn.innerHTML = _scrapeRunBtnHtml;
    statusEl.textContent = 'Server offline';
    statusEl.style.color = 'var(--red)';
    showToast('Server offline \u2014 cannot start scrape', 'error');
  }
}

const _scrapeRunBtnHtml = `<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none"
  stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
  <polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Run Scrape Now`;

// ── loadFromServer (init) ─────────────────────────────────────────────────
async function loadFromServer() {
  try {
    const [sRes, cRes, statusRes, logRes, agentRes] = await Promise.all([
      fetch('/api/settings'),
      fetch('/api/credentials'),
      fetch('/api/scrape-status').catch(() => null),
      fetch('/api/scrape-log?limit=50').catch(() => null),
      fetch('/api/agent/insights?lookback=400&max_reports=20').catch(() => null)
    ]);

    if (sRes.ok) populateSettings(await sRes.json());
    if (cRes.ok) populateCredentials(await cRes.json());

    if (statusRes?.ok) {
      const data = await statusRes.json();
      scrapeStatus = {};
      (data || []).forEach(s => { scrapeStatus[s.source + ':' + s.report_label] = s; });
      renderCuicReports();
      renderSmaxReports();
      updateDashboard(data);
    }

    if (logRes?.ok) renderScrapeLog(await logRes.json());
    if (agentRes?.ok) renderAgentInsights(await agentRes.json());
    else renderAgentInsights(null);

    // Mark as connected
    const si = document.getElementById('server-status');
    if (si) si.classList.remove('offline');
    const st = document.getElementById('server-status-text');
    if (st) st.textContent = 'Connected';

    setAutosaveStatus('', '\u2014');

  } catch(e) {
    console.warn('Server not available', e);
    const si = document.getElementById('server-status');
    if (si) si.classList.add('offline');
    const st = document.getElementById('server-status-text');
    if (st) st.textContent = 'Offline';
    resetDefaults();
    renderAgentInsights(null);
  }
}
