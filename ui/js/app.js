// ══════════════════════════════════════════════════════════════════════════
//  app.js — Sidebar navigation, toast, auto-save, helpers
// ══════════════════════════════════════════════════════════════════════════

// ── Helpers ──────────────────────────────────────────────────────────────
function esc(s)  { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function attr(s) { return (s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;'); }

function setBool(id, val, def) {
  const el = document.getElementById(id);
  if (el) el.checked = val !== undefined ? val : def;
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

// ── Sidebar Navigation ───────────────────────────────────────────────────
function switchPage(pageId) {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.page === pageId);
  });
  document.querySelectorAll('.page').forEach(page => {
    page.classList.toggle('active', page.id === 'page-' + pageId);
  });
}

function setWorkerSettingsExpanded(workerId, expanded) {
  const card = document.getElementById(workerId + '-connection-card');
  const toggle = document.getElementById(workerId + '-settings-toggle');
  if (!card || !toggle) return;

  card.classList.toggle('settings-card-hidden', !expanded);
  toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  toggle.setAttribute('title', expanded ? 'Hide settings' : 'Show settings');

  const text = toggle.querySelector('.worker-settings-toggle-text');
  if (text) text.textContent = expanded ? 'Hide settings' : 'Settings';

  try {
    localStorage.setItem('worker-settings:' + workerId, expanded ? 'expanded' : 'collapsed');
  } catch (e) {
    // Ignore storage failures; visibility still works for the current session.
  }
}

function toggleWorkerSettings(workerId) {
  const card = document.getElementById(workerId + '-connection-card');
  if (!card) return;
  setWorkerSettingsExpanded(workerId, card.classList.contains('settings-card-hidden'));
}

function initWorkerSettingsPanels() {
  ['cuic', 'smax'].forEach(workerId => {
    let expanded = false;
    try {
      expanded = localStorage.getItem('worker-settings:' + workerId) === 'expanded';
    } catch (e) {
      expanded = false;
    }
    setWorkerSettingsExpanded(workerId, expanded);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.nav-item[data-page]').forEach(item => {
    item.addEventListener('click', e => {
      e.preventDefault();
      switchPage(item.dataset.page);
    });
    item.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); switchPage(item.dataset.page); }
    });
  });

  initWorkerSettingsPanels();

  // Initial load
  loadFromServer();
});

// ── Toast ─────────────────────────────────────────────────────────────────
function showToast(msg, type = 'success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + type;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 3500);
}

// ── Copy to Clipboard ────────────────────────────────────────────────────
function copyToClipboard(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.select();
  document.execCommand('copy');
  showToast('Copied to clipboard!', 'success');
}

// ── Auto-Save ─────────────────────────────────────────────────────────────
let _autosaveTimer = null;
let _isDirty = false;

function markDirty() {
  _isDirty = true;
  setAutosaveStatus('unsaved', 'Unsaved changes');
  clearTimeout(_autosaveTimer);
  _autosaveTimer = setTimeout(_doAutosave, 1500);
}

async function _doAutosave() {
  if (!_isDirty) return;
  setAutosaveStatus('saving', 'Saving\u2026');
  try {
    const ok = await saveAll(true);
    if (ok) {
      _isDirty = false;
      setAutosaveStatus('saved', 'Saved');
      setTimeout(() => { if (!_isDirty) setAutosaveStatus('', '\u2014'); }, 4000);
    } else {
      setAutosaveStatus('error', 'Save failed');
    }
  } catch(e) {
    setAutosaveStatus('error', 'Save error');
  }
}

function setAutosaveStatus(state, label) {
  const wrapper = document.getElementById('autosave-status');
  const text    = document.getElementById('autosave-text');
  if (!wrapper || !text) return;
  wrapper.className = 'autosave-status' + (state ? ' ' + state : '');
  text.textContent = label;
}

// ── Developer Tools ───────────────────────────────────────────────────────
async function clearAllData() {
  if (!confirm('This will permanently delete ALL data from the database and the CSV file.\n\nThis cannot be undone. Continue?')) return;
  try {
    const res  = await fetch('/api/clear-data', { method: 'POST' });
    const data = await res.json();
    if (data.error) { showToast('Error: ' + data.error, 'error'); return; }
    showToast('Database and CSV cleared successfully.', 'success');
  } catch(e) {
    showToast('Clear failed: ' + e.message, 'error');
  }
}
