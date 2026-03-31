// ══════════════════════════════════════════════════════════════════════════
//  settings-io.js — Build, populate, save, export, import
// ══════════════════════════════════════════════════════════════════════════

// ── syncReportInputs: flush DOM values into state arrays ─────────────────
function syncReportInputs() {
  document.querySelectorAll('#cuic-reports-list .report-card').forEach((card, i) => {
    const inputs = card.querySelectorAll('.inline-row input');
    if (inputs[0]) {
      const path = inputs[0].value.trim();
      const lastSlash = path.lastIndexOf('/');
      if (lastSlash === -1) {
        cuicReports[i].folder = '';
        cuicReports[i].name = path;
      } else {
        cuicReports[i].folder = path.substring(0, lastSlash);
        cuicReports[i].name = path.substring(lastSlash + 1);
      }
    }
    if (inputs[1]) cuicReports[i].label = inputs[1].value;
  });
  document.querySelectorAll('#smax-reports-list .report-card').forEach((card, i) => {
    const inputs = card.querySelectorAll('.inline-row input');
    if (inputs[0]) smaxReports[i].label = inputs[0].value;
    if (inputs[1]) smaxReports[i].url   = inputs[1].value;
  });
}

// ── buildSettings ────────────────────────────────────────────────────────
function buildSettings() {
  syncReportInputs();
  return {
    global: {
      headless:             document.getElementById('g-headless').checked,
      use_system_chrome:    document.getElementById('g-system-chrome').checked,
      screenshot_steps:     document.getElementById('g-screenshot-steps').checked,
      screenshot_errors:    document.getElementById('g-screenshot-errors').checked,
      log_level:            document.getElementById('g-log-level').value,
      output_dir:           document.getElementById('g-output-dir').value,
      log_dir:              document.getElementById('g-log-dir').value,
      data_retention_days:  parseInt(document.getElementById('g-retention').value) || 90,
      shared_drive_csv:     document.getElementById('g-shared-drive').value
    },
    workers: {
      cuic: {
        enabled:            document.getElementById('cuic-enabled').checked,
        url:                document.getElementById('cuic-url').value,
        reports:            cuicReports.map(r => {
          const f = Object.assign({}, r.filters || {});
          if (r._wizard_meta) f._meta = r._wizard_meta;
          const meta = r._wizard_meta || f._meta;
          const steps = meta && meta.steps;
          if (steps && Array.isArray(steps)) {
            steps.forEach((stepMeta, i) => {
              const stepKey = 'step_' + (i + 1);
              const stepVals = f[stepKey];
              if (!stepVals || typeof stepVals !== 'object') return;
              const params = stepMeta.params || [];
              const normalized = {};
              params.forEach(p => {
                const pn = (p.paramName || '').trim();
                const label = (p.label || '').trim();
                if (!pn) return;
                let val = stepVals[pn];
                if (val === undefined && label) val = stepVals[label];
                if (val !== undefined) normalized[pn] = val;
              });
              ['_field_filters'].forEach(k => { if (stepVals[k] !== undefined) normalized[k] = stepVals[k]; });
              if (Object.keys(normalized).length) f[stepKey] = normalized;
            });
          }
          return {
            label: r.label, folder: r.folder, name: r.name,
            enabled: r.enabled !== false, data_type: r.data_type || 'ongoing',
            row_mode: r.row_mode || 'consolidated_only',
            columns: r.columns !== undefined ? r.columns : null,
            ...(r._columns_meta ? { _columns_meta: r._columns_meta } : {}),
            filters: f
          };
        }),
        timeout_nav_ms:     parseInt(document.getElementById('cuic-t-nav').value)    || 30000,
        timeout_short_ms:   parseInt(document.getElementById('cuic-t-short').value)  || 1500,
        timeout_medium_ms:  parseInt(document.getElementById('cuic-t-medium').value) || 2500,
        timeout_long_ms:    parseInt(document.getElementById('cuic-t-long').value)   || 8000
      },
      smax: {
        enabled:                 document.getElementById('smax-enabled').checked,
        base_url:                document.getElementById('smax-url').value,
        reports:                 smaxReports.map(r => ({
          label: r.label, url: r.url, enabled: r.enabled !== false,
          data_type: r.data_type || 'ongoing',
          properties: r.properties || {}
        })),
        page_load_timeout_ms:    parseInt(document.getElementById('smax-t-load').value)    || 120000,
        element_wait_timeout_ms: parseInt(document.getElementById('smax-t-elem').value)    || 30000,
        tab_stagger_delay_ms:    parseInt(document.getElementById('smax-t-stagger').value) || 2000,
        max_retries:             parseInt(document.getElementById('smax-retries').value)   || 2
      }
    }
  };
}

// ── buildCredentials ─────────────────────────────────────────────────────
function buildCredentials() {
  return {
    cuic: { username: document.getElementById('cuic-user').value, password: document.getElementById('cuic-pass').value },
    smax: { username: document.getElementById('smax-user').value, password: document.getElementById('smax-pass').value }
  };
}

// ── populateSettings ─────────────────────────────────────────────────────
function populateSettings(s) {
  const g = s.global || {};
  setBool('g-headless',         g.headless,            true);
  setBool('g-system-chrome',    g.use_system_chrome,   true);
  setBool('g-screenshot-steps', g.screenshot_steps,    false);
  setBool('g-screenshot-errors',g.screenshot_errors,   true);
  setVal('g-log-level',  g.log_level  || 'INFO');
  setVal('g-output-dir', g.output_dir || 'output');
  setVal('g-log-dir',    g.log_dir    || 'logs');
  setVal('g-retention',  g.data_retention_days || 90);
  setVal('g-shared-drive', g.shared_drive_csv || '');

  const cuic = (s.workers || {}).cuic || {};
  setBool('cuic-enabled', cuic.enabled, true);
  setVal('cuic-url', cuic.url || 'https://148.151.32.77:8444/cuicui/Main.jsp');
  cuicReports = (cuic.reports || []).map(r => {
    const rep = {
      label: r.label||'', folder: r.folder||'', name: r.name||'',
      enabled: r.enabled !== false, data_type: r.data_type || 'ongoing',
      row_mode: r.row_mode || 'consolidated_only',
      columns: r.columns !== undefined ? r.columns : null,
      filters: r.filters || {}
    };
    if (rep.filters._meta) rep._wizard_meta = rep.filters._meta;
    if (r._columns_meta) rep._columns_meta = r._columns_meta;
    return rep;
  });
  if (!cuicReports.length) {
    cuicReports.push({ label:'call_type_hist', folder:'Test', name:'Z Call Type Historical All Fields', enabled:true, data_type:'ongoing', filters:{} });
  }
  renderCuicReports();
  setVal('cuic-t-nav',    cuic.timeout_nav_ms    || 30000);
  setVal('cuic-t-short',  cuic.timeout_short_ms  || 1500);
  setVal('cuic-t-medium', cuic.timeout_medium_ms || 2500);
  setVal('cuic-t-long',   cuic.timeout_long_ms   || 8000);

  const smax = (s.workers || {}).smax || {};
  setBool('smax-enabled', smax.enabled, false);
  setVal('smax-url', smax.base_url || 'https://smax.corp.pdo.om');
  smaxReports = (smax.reports || []).map(r => ({
    label: r.label||'', url: r.url||'', enabled: r.enabled !== false,
    data_type: r.data_type || 'ongoing', properties: r.properties || {}
  }));
  renderSmaxReports();
  setVal('smax-t-load',    smax.page_load_timeout_ms    || 120000);
  setVal('smax-t-elem',    smax.element_wait_timeout_ms || 30000);
  setVal('smax-t-stagger', smax.tab_stagger_delay_ms    || 2000);
  setVal('smax-retries',   smax.max_retries             || 2);
}

// ── populateCredentials ──────────────────────────────────────────────────
function populateCredentials(c) {
  setVal('cuic-user', (c.cuic||{}).username||'');
  setVal('cuic-pass', (c.cuic||{}).password||'');
  setVal('smax-user', (c.smax||{}).username||'');
  setVal('smax-pass', (c.smax||{}).password||'');
}

// ── saveAll ──────────────────────────────────────────────────────────────
async function saveAll(silent = false) {
  try {
    const [r1, r2] = await Promise.all([
      fetch('/api/settings',    { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(buildSettings()) }),
      fetch('/api/credentials', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(buildCredentials()) })
    ]);
    if (r1.ok && r2.ok) {
      if (!silent) showToast('Settings saved!', 'success');
      return true;
    }
    if (!silent) showToast('Save failed', 'error');
    return false;
  } catch(e) {
    if (!silent) showToast('Server offline \u2014 use Export tab to copy JSON manually', 'error');
    return false;
  }
}

// ── generateJSON ─────────────────────────────────────────────────────────
function generateJSON() {
  const outSettings = document.getElementById('out-settings');
  const outCreds    = document.getElementById('out-credentials');
  if (outSettings) outSettings.value = JSON.stringify(buildSettings(), null, 2);
  if (outCreds)    outCreds.value    = JSON.stringify(buildCredentials(), null, 2);
  switchPage('export');
  showToast('JSON generated!', 'success');
}

// ── loadFromJSON ─────────────────────────────────────────────────────────
function loadFromJSON() {
  try {
    const st = (document.getElementById('in-settings') || {}).value || '';
    const ct = (document.getElementById('in-credentials') || {}).value || '';
    if (st.trim()) populateSettings(JSON.parse(st.trim()));
    if (ct.trim()) populateCredentials(JSON.parse(ct.trim()));
    showToast('Form populated from JSON', 'info');
  } catch(e) {
    showToast('Invalid JSON: ' + e.message, 'error');
  }
}

// ── resetDefaults ────────────────────────────────────────────────────────
function resetDefaults() {
  populateSettings({
    global: {
      headless: true, use_system_chrome: true, screenshot_steps: false, screenshot_errors: true,
      log_level: 'INFO', output_dir: 'output', log_dir: 'logs', data_retention_days: 90, shared_drive_csv: ''
    },
    workers: {
      cuic: {
        enabled: true, url: 'https://148.151.32.77:8444/cuicui/Main.jsp',
        reports: [
          { label:'call_type_hist', folder:'Test', name:'Z Call Type Historical All Fields', enabled:true, data_type:'ongoing', filters:{} },
          { label:'agent_hist', folder:'Stock/CCE/CCE_AF_Historical', name:'Agent Historical All Fields', enabled:true, data_type:'ongoing', filters:{} }
        ],
        timeout_nav_ms: 30000, timeout_short_ms: 1500, timeout_medium_ms: 2500, timeout_long_ms: 8000
      },
      smax: {
        enabled: false, base_url: 'https://smax.corp.pdo.om', reports: [],
        page_load_timeout_ms: 120000, element_wait_timeout_ms: 30000,
        tab_stagger_delay_ms: 2000, max_retries: 2
      }
    }
  });
  populateCredentials({ cuic:{username:'',password:''}, smax:{username:'',password:''} });
  showToast('Reset to defaults', 'info');
}
