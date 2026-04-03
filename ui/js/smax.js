// ══════════════════════════════════════════════════════════════════════════
//  smax.js — SMAX report cards, properties panel, discover properties
// ══════════════════════════════════════════════════════════════════════════

// ── STATE ─────────────────────────────────────────────────────────────────
let smaxReports = [];

function hasSmaxGeneratedFields(report) {
  const props = report.properties || {};
  return Boolean(report.label || props.report_name || Object.keys(props).length > 0);
}

function resetSmaxDiscovery(report) {
  report.label = '';
  report.properties = {};
}

function updateSmaxReportUrl(idx, url) {
  const report = smaxReports[idx];
  const nextUrl = (url || '').trim();
  const previousUrl = (report.url || '').trim();
  report.url = nextUrl;
  if (previousUrl !== nextUrl) resetSmaxDiscovery(report);
  renderSmaxReports();
  markDirty();
}

// ══════════════════════════════════════════════════════════════════════════
//  SMAX REPORT CARDS
// ══════════════════════════════════════════════════════════════════════════

function renderSmaxReports() {
  const container = document.getElementById('smax-reports-list');
  if (!container) return;
  if (smaxReports.length === 0) {
    container.innerHTML = '<p style="color:var(--muted);text-align:center;padding:20px">No reports configured. Click \u201c+ Add Report\u201d to get started.</p>';
    return;
  }
  container.innerHTML = smaxReports.map((r, i) => {
    const isPendingValidation = !hasSmaxGeneratedFields(r);

    if (isPendingValidation) {
      return `<div class="report-card">
        <div class="report-card-header">
          <span class="label-tag" style="color:var(--muted);font-style:italic">New Report</span>
          <button class="btn btn-icon" onclick="removeSmaxReport(${i})" title="Remove"><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='3 6 5 6 21 6'/><path d='M19 6l-1 14H6L5 6'/><path d='M10 11v6'/><path d='M14 11v6'/><path d='M9 6V4h6v2'/></svg></button>
        </div>
        <div class="inline-row"><label>Report URL</label><input data-report-field="url" value="${attr(r.url||'')}" onchange="updateSmaxReportUrl(${i}, this.value)" placeholder="https://smax.corp.pdo.om/reports/report/\u2026" style="grid-column:2"></div>
        <div style="margin-top:10px;display:flex;align-items:center;gap:8px;">
          <button class="btn-discover" id="smax-discover-btn-${i}" onclick="discoverSmaxProperties(${i})">
            \u25B6 Validate Link
          </button>
          <span style="font-size:11px;color:var(--muted)">Opens browser to validate the URL and fetch report properties</span>
        </div>
      </div>`;
    }

    const st = scrapeStatus['smax:' + r.label];
    let statusHtml = '<div class="status-bar"><span class="status-dot pending"></span> Never scraped</div>';
    if (st) {
      const icon = st.status === 'success' ? '\u2705' : st.status === 'error' ? '\u274C' : '\u26A0\uFE0F';
      const dur  = st.duration_s ? st.duration_s.toFixed(1) + 's' : '';
      const msg  = st.message ? ' \u2014 ' + esc(st.message) : '';
      statusHtml = `<div class="status-bar"><span class="status-dot ${st.status}"></span>
        <span>${icon} ${esc(st.timestamp)} \u00B7 ${st.row_count || 0} rows \u00B7 ${dur}${msg}</span></div>`;
    }
    const propsHtml = renderSmaxPropertiesPanel(r, i);
    return `<div class="report-card ${r.enabled ? '' : 'disabled'}">
      <div class="report-card-header">
        <div style="display:flex;align-items:center;gap:8px">
          <span class="label-tag">${esc(r.label || 'unnamed')}</span>
          <span class="data-type-badge ${r.data_type === 'historical' ? 'historical' : 'ongoing'}">${r.data_type === 'historical' ? '\ud83d\udce6 Historical' : '\ud83d\udce1 Ongoing'}</span>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <div class="toggle-switch" style="margin:0">
            <input type="checkbox" id="smax-rpt-en-${i}" ${r.enabled ? 'checked' : ''}
              onchange="smaxReports[${i}].enabled=this.checked;renderSmaxReports();markDirty()">
            <label for="smax-rpt-en-${i}" style="font-size:12px">Enabled</label>
          </div>
          <button class="btn btn-icon" onclick="removeSmaxReport(${i})" title="Remove"><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='3 6 5 6 21 6'/><path d='M19 6l-1 14H6L5 6'/><path d='M10 11v6'/><path d='M14 11v6'/><path d='M9 6V4h6v2'/></svg></button>
        </div>
      </div>
      <div class="inline-row"><label>Label</label><input data-report-field="label" value="${attr(r.label||'')}" onchange="smaxReports[${i}].label=this.value;markDirty()" placeholder="e.g. sla_fcr_month"></div>
      <div class="inline-row"><label>Report URL</label><input data-report-field="url" value="${attr(r.url||'')}" onchange="updateSmaxReportUrl(${i}, this.value)" placeholder="https://smax.corp.pdo.om/reports/report/\u2026"></div>
      <div class="inline-row"><label>Data Type</label>
        <select onchange="smaxReports[${i}].data_type=this.value;renderSmaxReports();markDirty()">
          <option value="ongoing" ${(r.data_type||'ongoing')==='ongoing'?'selected':''}>📡 Ongoing (re-scrape every run)</option>
          <option value="historical" ${r.data_type==='historical'?'selected':''}>📦 Historical (scrape once)</option>
        </select>
      </div>
      <div style="margin-top:10px;display:flex;align-items:center;gap:8px;">
        <button class="btn-discover" id="smax-discover-btn-${i}" onclick="discoverSmaxProperties(${i})">
          \u25B6 Re-validate Link
        </button>
        <span style="font-size:11px;color:var(--muted)">Re-open browser to update report properties</span>
      </div>
      ${propsHtml}
      ${statusHtml}
    </div>`;
  }).join('');
}

function addSmaxReport() {
  const hasEmpty = smaxReports.some(r => !r.label && !r.url);
  if (hasEmpty) { showToast('Please fill in the existing empty report first', 'warning'); return; }
  smaxReports.unshift({ label: '', url: '', enabled: true, data_type: 'ongoing', properties: {} });
  renderSmaxReports();
  markDirty();
  setTimeout(() => {
    const first = document.getElementById('smax-reports-list').firstElementChild;
    if (first) { first.classList.add('highlight-new'); setTimeout(() => first.classList.remove('highlight-new'), 1000); }
  }, 50);
}

function removeSmaxReport(i) {
  if (i < 0 || i >= smaxReports.length) return;
  smaxReports.splice(i, 1);
  renderSmaxReports();
  markDirty();
}

// ══════════════════════════════════════════════════════════════════════════
//  PROPERTIES PANEL RENDERER
// ══════════════════════════════════════════════════════════════════════════

function renderSmaxPropertiesPanel(report, idx) {
  const props = report.properties || {};
  if (!props.report_name && !props.filters) return '';

  let html = '<details class="filter-panel-collapsible"><summary class="filter-panel-toggle">\uD83D\uDCC4 Report Properties</summary><div class="filter-panel">';

  if (props.report_name) html += `<div class="smax-prop-row"><span class="smax-prop-label">Report Name</span><span>${esc(props.report_name)}</span></div>`;
  if (props.record_type) html += `<div class="smax-prop-row"><span class="smax-prop-label">Record Type</span><span class="smax-prop-badge">${esc(props.record_type)}</span></div>`;
  if (props.group_by?.length) html += `<div class="smax-prop-row"><span class="smax-prop-label">Group By</span><span>${props.group_by.map(g => esc(g)).join(', ')}</span></div>`;
  if (props.func && (props.func.main || props.func.secondary)) {
    html += `<div class="smax-prop-row"><span class="smax-prop-label">Function</span><span>${esc([props.func.main, props.func.secondary].filter(Boolean).join(' by '))}</span></div>`;
  }
  if (props.chart_function) html += `<div class="smax-prop-row"><span class="smax-prop-label">Chart Function</span><span>${esc(props.chart_function)}</span></div>`;

  const filters = props.filters || [];
  if (filters.length) {
    html += '<div style="margin-top:10px"><strong style="font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px">Filters</strong></div>';
    filters.forEach(f => {
      const negBadge = f.negated ? '<span class="smax-neg-badge">NOT</span> ' : '';
      const opBadge  = f.operator && f.operator !== 'Is' ? `<span class="smax-op-badge">${esc(f.operator)}</span> ` : '';
      let valueHtml  = '';

      if (f.type === 'date') {
        valueHtml = `<span class="smax-filter-value">${esc(f.display_value || '')}</span>`;
        if (f.date_presets?.length) {
          valueHtml += `<div class="smax-presets">Presets: ${f.date_presets.map(p => '<span class="smax-preset-tag">' + esc(p.label) + '</span>').join(' ')}</div>`;
        }
      } else if (f.type === 'enum') {
        valueHtml = negBadge + esc(f.display_value || '');
        if (f.enum_options?.length) {
          valueHtml += '<div class="smax-enum-opts">' + f.enum_options.map(o =>
            `<span class="smax-enum-opt${o.checked ? ' active' : ''}">${esc(o.label)}</span>`
          ).join(' ') + '</div>';
        }
      } else if (f.selected_values?.length) {
        valueHtml = f.selected_values.map(v => '<span class="smax-chip">' + esc(v) + '</span>').join(' ');
      } else if (f.display_value?.includes(',')) {
        valueHtml = f.display_value.split(',').map(v => v.trim()).filter(Boolean)
          .map(v => '<span class="smax-chip">' + esc(v) + '</span>').join(' ');
      } else {
        valueHtml = esc(f.display_value || '');
      }

      html += `<div class="smax-filter-row">
        <span class="smax-filter-label">${esc(f.field_label || f.field_id || '?')}</span>
        <span class="smax-filter-sep">:</span>
        <span>${opBadge}${f.type !== 'enum' ? negBadge : ''}${valueHtml}</span>
      </div>`;
    });
  }

  if (props.chart_legend?.length) {
    html += '<div style="margin-top:10px"><strong style="font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px">Chart Legend</strong></div>';
    props.chart_legend.forEach(item => {
      html += `<div class="smax-prop-row"><span>${esc(item.label)}</span><span style="color:var(--accent)">${esc(item.value || '')}</span></div>`;
    });
  }

  html += `<div style="margin-top:8px">
    <button class="btn-discover" style="font-size:11px;padding:4px 10px" onclick="discoverSmaxProperties(${idx})">\u25B6 Re-discover</button>
    <button class="btn-discover" style="font-size:11px;padding:4px 10px;margin-left:4px" onclick="clearSmaxProperties(${idx})">\u2716 Clear</button>
  </div>`;
  html += '</div></details>';
  return html;
}

function clearSmaxProperties(idx) {
  smaxReports[idx].properties = {};
  renderSmaxReports();
  markDirty();
  showToast('Properties cleared', 'info');
}

// ── Auto-detect data type from date filter presets ───────────────────────
function suggestDataType(props) {
  const filters = props.filters || [];
  const dateFilters = filters.filter(f => f.type === 'date');
  if (!dateFilters.length) return null;
  const allText = dateFilters.map(f => {
    const parts = [f.display_value || ''];
    (f.date_presets || []).forEach(p => parts.push(p.label || ''));
    return parts.join(' ');
  }).join(' ').toLowerCase();
  const histPat    = /previous\s+month|last\s+month|previous\s+year|last\s+year|previous\s+quarter|last\s+quarter|yesterday/;
  const ongoingPat = /this\s+month|current\s+month|today|this\s+year|current\s+year|this\s+quarter|current\s+quarter|this\s+week|current\s+week|rolling/;
  const hasH = histPat.test(allText), hasO = ongoingPat.test(allText);
  if (hasH && !hasO) return 'historical';
  if (hasO) return 'ongoing';
  return null;
}

// ══════════════════════════════════════════════════════════════════════════
//  DISCOVER SMAX PROPERTIES
// ══════════════════════════════════════════════════════════════════════════

async function discoverSmaxProperties(idx) {
  const r   = smaxReports[idx];
  const btn = document.getElementById('smax-discover-btn-' + idx);

  if (!r.url) { showToast('Set the report URL first', 'error'); return; }

  const origHtml = btn.innerHTML;
  btn.innerHTML  = '<span class="spinner"></span> Discovering\u2026';
  btn.disabled   = true;
  showToast('Launching browser to read report properties\u2026 This may take 30\u201360s.', 'info');

  try {
    const res  = await fetch('/api/discover-smax-properties', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ url: r.url })
    });
    const data = await res.json();

    if (data.error) { showToast('Discovery error: ' + data.error, 'error'); return; }

    r.properties = data;

    if (!r.label && data.report_name) r.label = generateLabelFromName(data.report_name);

    const suggested = suggestDataType(data);
    if (suggested) r.data_type = suggested;

    const filterCount = (data.filters || []).length;
    const typeLabel   = r.data_type === 'historical' ? ' (auto-detected: historical)' : ' (auto-detected: ongoing)';
    showToast(`Discovered: "${data.report_name || 'report'}" with ${filterCount} filter(s)${suggested ? typeLabel : ''}!`, 'success');
    renderSmaxReports();
    markDirty();

  } catch(e) {
    showToast('Discovery failed: ' + e.message, 'error');
  } finally {
    btn.innerHTML = origHtml;
    btn.disabled  = false;
  }
}
