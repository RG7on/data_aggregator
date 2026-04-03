// ══════════════════════════════════════════════════════════════════════════
//  cuic.js — CUIC report cards, filter wizard, discover filters
// ══════════════════════════════════════════════════════════════════════════

// ── STATE ─────────────────────────────────────────────────────────────────
let cuicReports = [];
let scrapeStatus = {};

function getCuicStatusKey(report) {
  return 'cuic:' + ((report && (report.report_id || report.label)) || '');
}

function normalizeCuicReportPath(path) {
  return (path || '').replace(/\\+/g, '/').replace(/\/+/g, '/').trim().replace(/^\/+|\/+$/g, '');
}

function splitCuicReportPath(path) {
  const normalized = normalizeCuicReportPath(path);
  const lastSlash = normalized.lastIndexOf('/');
  if (lastSlash === -1) return { path: normalized, folder: '', name: normalized };
  return {
    path: normalized,
    folder: normalized.substring(0, lastSlash),
    name: normalized.substring(lastSlash + 1)
  };
}

function getCuicReportPath(report) {
  return (report.folder ? report.folder + '/' : '') + (report.name || '');
}

function hasCuicGeneratedFields(report) {
  const filters = report.filters || {};
  return Boolean(report.label || report._wizard_meta || report._columns_meta || Object.keys(filters).length > 0);
}

function resetCuicDiscovery(report) {
  report.label = '';
  report.filters = {};
  delete report._wizard_meta;
  delete report._columns_meta;
}

function cloneCuicData(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function uniqueCuicStrings(values) {
  const seen = new Set();
  const out = [];
  (values || []).forEach(value => {
    const normalized = String(value || '').trim();
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    out.push(normalized);
  });
  return out;
}

function getCuicParamKey(param) {
  return uniqueCuicStrings([
    param && param.storageKey,
    param && param.paramName,
    param && param.label
  ])[0] || '';
}

function getCuicParamAliases(param) {
  return uniqueCuicStrings([
    getCuicParamKey(param),
    ...(Array.isArray(param && param.aliases) ? param.aliases : []),
    param && param.paramName,
    param && param.paramName2,
    param && param.label
  ]);
}

function getCuicSavedValue(container, param) {
  const source = container || {};
  for (const alias of getCuicParamAliases(param)) {
    if (Object.prototype.hasOwnProperty.call(source, alias)) return source[alias];
  }
  return undefined;
}

function normalizeFieldFilterConfigs(value, fallbackFields) {
  const fields = Array.isArray(fallbackFields) ? fallbackFields : [];
  const toFieldId = item => {
    if (!item || typeof item !== 'object') return '';
    return String(item.fieldId || item.id || item.label || '').trim();
  };

  if (value === 'all') {
    return fields
      .map(field => {
        const id = toFieldId(field);
        if (!id) return null;
        return {
          id,
          fieldId: id,
          label: field.label || id,
          operator: '',
          value1: '',
          value2: '',
          showInput2: false
        };
      })
      .filter(Boolean);
  }

  if (!Array.isArray(value)) return [];

  return value
    .map(item => {
      if (typeof item === 'string') {
        const id = item.trim();
        if (!id) return null;
        const field = fields.find(f => toFieldId(f) === id);
        return {
          id,
          fieldId: id,
          label: field?.label || id,
          operator: '',
          value1: '',
          value2: '',
          showInput2: false
        };
      }
      if (!item || typeof item !== 'object') return null;
      const id = toFieldId(item);
      if (!id) return null;
      const field = fields.find(f => toFieldId(f) === id);
      return {
        ...cloneCuicData(item),
        id,
        fieldId: id,
        label: item.label || field?.label || id,
        operator: item.operator || '',
        value1: item.value1 !== undefined ? String(item.value1) : '',
        value2: item.value2 !== undefined ? String(item.value2) : '',
        showInput2: !!item.showInput2
      };
    })
    .filter(Boolean);
}

// ══════════════════════════════════════════════════════════════════════════
//  CUIC REPORT CARDS
// ══════════════════════════════════════════════════════════════════════════

function renderCuicReports() {
  const container = document.getElementById('cuic-reports-list');
  if (!container) return;
  if (cuicReports.length === 0) {
    container.innerHTML = '<p style="color:var(--muted);text-align:center;padding:20px">No reports configured. Click \u201c+ Add Report\u201d to get started.</p>';
    return;
  }
  container.innerHTML = cuicReports.map((r, i) => {
    const isPendingValidation = !hasCuicGeneratedFields(r);
    const reportPath = getCuicReportPath(r);

    if (isPendingValidation) {
      return `<div class="report-card">
        <div class="report-card-header">
          <span class="label-tag" style="color:var(--muted);font-style:italic">New Report</span>
          <button class="btn btn-icon" onclick="removeCuicReport(${i})" title="Remove"><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='3 6 5 6 21 6'/><path d='M19 6l-1 14H6L5 6'/><path d='M10 11v6'/><path d='M14 11v6'/><path d='M9 6V4h6v2'/></svg></button>
        </div>
        <div class="inline-row"><label>Report Path</label><input data-report-field="path" value="${attr(reportPath)}" onchange="updateCuicReportPath(${i}, this.value)" placeholder="e.g. Test/Z Call Type Historical All Fields" style="grid-column:2"></div>
        <div style="margin-top:10px;display:flex;align-items:center;gap:8px;">
          <button class="btn-discover" id="discover-btn-${i}" onclick="discoverFilters(${i})">
            \u25B6 Validate Path
          </button>
          <span style="font-size:11px;color:var(--muted)">Opens browser to validate the report path and read filters</span>
        </div>
      </div>`;
    }

    const st = scrapeStatus[getCuicStatusKey(r)];
    let statusHtml = '<div class="status-bar"><span class="status-dot pending"></span> Never scraped</div>';
    if (st) {
      const icon = st.status === 'success' ? '\u2705' : st.status === 'error' ? '\u274C' : '\u26A0\uFE0F';
      const dur  = st.duration_s ? st.duration_s.toFixed(1) + 's' : '';
      const msg  = st.message ? ' \u2014 ' + esc(st.message) : '';
      statusHtml = `<div class="status-bar"><span class="status-dot ${st.status}"></span>
        <span>${icon} ${esc(st.timestamp)} \u00B7 ${st.row_count || 0} rows \u00B7 ${dur}${msg}</span></div>`;
    }
    const filterHtml = renderFilterPanel(r, i);
    return `<div class="report-card ${r.enabled ? '' : 'disabled'}">
      <div class="report-card-header">
        <div style="display:flex;align-items:center;gap:8px">
          <span class="label-tag">${esc(r.label || 'unnamed')}</span>
          <span class="data-type-badge ${r.data_type === 'historical' ? 'historical' : 'ongoing'}">${r.data_type === 'historical' ? '\ud83d\udce6 Historical' : '\ud83d\udce1 Ongoing'}</span>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <div class="toggle-switch" style="margin:0">
            <input type="checkbox" id="rpt-en-${i}" ${r.enabled ? 'checked' : ''}
              onchange="cuicReports[${i}].enabled=this.checked;renderCuicReports();markDirty()">
            <label for="rpt-en-${i}" style="font-size:12px">Enabled</label>
          </div>
          <button class="btn btn-icon" onclick="removeCuicReport(${i})" title="Remove"><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='3 6 5 6 21 6'/><path d='M19 6l-1 14H6L5 6'/><path d='M10 11v6'/><path d='M14 11v6'/><path d='M9 6V4h6v2'/></svg></button>
        </div>
      </div>
      <div class="inline-row"><label>Report Path</label><input data-report-field="path" value="${attr(reportPath)}" onchange="updateCuicReportPath(${i}, this.value)" placeholder="e.g. Test/Z Call Type Historical All Fields"></div>
      <div class="inline-row"><label>Label</label><input data-report-field="label" value="${attr(r.label)}" onchange="cuicReports[${i}].label=this.value;markDirty()" placeholder="Auto-generated from report name"></div>
      <div class="inline-row"><label>Data Type</label>
        <select onchange="cuicReports[${i}].data_type=this.value;renderCuicReports();markDirty()">
          <option value="ongoing" ${(r.data_type||'ongoing')==='ongoing'?'selected':''}>📡 Ongoing (re-scrape every run)</option>
          <option value="historical" ${r.data_type==='historical'?'selected':''}>📦 Historical (scrape once)</option>
        </select>
      </div>
      <div class="inline-row"><label>Row Mode</label>
        <div class="row-mode-seg">
          <button type="button" class="${(r.row_mode||'consolidated_only')==='consolidated_only'?'active':''}" onclick="cuicReports[${i}].row_mode='consolidated_only';renderCuicReports();markDirty()">📊 Consolidated only</button>
          <button type="button" class="${r.row_mode==='all'?'active':''}" onclick="cuicReports[${i}].row_mode='all';renderCuicReports();markDirty()">🔢 All rows</button>
        </div>
      </div>
      <div style="margin-top:10px;display:flex;align-items:center;gap:8px;">
        <button class="btn-discover" id="discover-btn-${i}" onclick="discoverFilters(${i})">
          \u25B6 Re-validate Path
        </button>
        <span style="font-size:11px;color:var(--muted)">Re-open browser to update report filters</span>
      </div>
      ${filterHtml}
      ${renderColumnsPanel(r, i)}
      ${statusHtml}
    </div>`;
  }).join('');
}

function addCuicReport() {
  const hasEmpty = cuicReports.some(r => !r.folder && !r.name);
  if (hasEmpty) { showToast('Please fill in the existing empty report first', 'warning'); return; }
  cuicReports.unshift({ report_id: '', label: '', folder: '', name: '', enabled: true, data_type: 'ongoing', filters: {} });
  renderCuicReports();
  markDirty();
  setTimeout(() => {
    const first = document.getElementById('cuic-reports-list').firstElementChild;
    if (first) { first.classList.add('highlight-new'); setTimeout(() => first.classList.remove('highlight-new'), 1000); }
  }, 50);
}

function removeCuicReport(i) {
  if (i < 0 || i >= cuicReports.length) return;
  cuicReports.splice(i, 1);
  renderCuicReports();
  markDirty();
}

function generateLabelFromName(name) {
  if (!name) return '';
  return name.trim().replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase();
}

function updateCuicReportPath(idx, path) {
  const report = cuicReports[idx];
  const nextPath = normalizeCuicReportPath(path);
  const previousPath = getCuicReportPath(report);
  const parsed = splitCuicReportPath(nextPath);
  report.folder = parsed.folder;
  report.name = parsed.name;
  if (previousPath !== getCuicReportPath(report)) resetCuicDiscovery(report);
  renderCuicReports();
  markDirty();
}

// ══════════════════════════════════════════════════════════════════════════
//  FILTER PANEL RENDERER
// ══════════════════════════════════════════════════════════════════════════

function renderFilterPanel(report, idx) {
  const filters = report.filters || {};
  const meta = report._wizard_meta || filters._meta || null;

  if (!meta) {
    if (Object.keys(filters).length > 0) {
      return `<details class="filter-panel-collapsible"><summary class="filter-panel-toggle">\uD83C\uDFA8 Saved Filters (raw)</summary><div class="filter-panel">
        <pre style="font-size:11px;color:var(--muted);overflow-x:auto;">${esc(JSON.stringify(filters,null,2))}</pre>
        <button class="btn-discover" style="margin-top:6px" onclick="discoverFilters(${idx})">\u25B6 Re-discover</button>
      </div></details>`;
    }
    return '';
  }

  const isCuic      = meta.type === 'cuic_spab';
  const isMultiStep = meta.type === 'cuic_multistep';
  const icon = isMultiStep ? '\uD83E\uDDE9' : (isCuic ? '\uD83C\uDFAF' : '\uD83C\uDFA8');

  let html = `<details class="filter-panel-collapsible"><summary class="filter-panel-toggle">${icon} Filter Wizard Settings
      <span class="filter-clear" onclick="event.stopPropagation();clearFilters(${idx})">\u2716 Clear all</span>
    </summary><div class="filter-panel">`;

  if (isMultiStep) {
    const steps      = meta.steps || [];
    const stepTitles = meta.stepTitles || steps.map((s,i) => 'Step ' + (i+1));

    html += `<div class="wizard-step-tabs" id="wst-${idx}">`;
    stepTitles.forEach((title, si) => {
      if (si > 0) html += `<span class="wst-arrow">\u25B6</span>`;
      html += `<span class="wst-tab${si===0?' active':''}" onclick="switchWizardTab(${idx},${si})">${esc(title)}</span>`;
    });
    html += `</div>`;

    steps.forEach((step, si) => {
      const stepKey   = 'step_' + step.step;
      const savedStep = filters[stepKey] || {};
      html += `<div class="wizard-step-body${si === 0 ? ' active' : ''}" id="wsb-${idx}-${si}">`;

      (step.params || []).forEach(p => {
        const paramKey = getCuicParamKey(p);
        const label = p.label || p.paramName || paramKey;
        const savedVal = getCuicSavedValue(savedStep, p);

        if (p.type === 'cuic_datetime') {
          const cfg       = typeof savedVal === 'string' ? {preset: savedVal} : (savedVal && typeof savedVal === 'object' ? savedVal : {});
          const curPreset = cfg.preset || '';
          const presets   = p.datePresets || [];
          let opts = `<option value="" ${!curPreset?'selected':''}>\u2014 use default \u2014</option>`;
          opts += presets.map(o => `<option value="${attr(o.value)}"${curPreset===o.value?' selected':''}>${esc(o.label)}</option>`).join('');
          const dtId = 'dt-' + idx + '-s' + step.step + '-' + paramKey.replace(/[^a-zA-Z0-9]/g,'_');

          html += `<div class="filter-field"><label title="${attr(paramKey)}">${esc(label)}</label>
            <select id="${dtId}-preset" onchange="updateMsDatetime(${idx},'${attr(stepKey)}','${attr(paramKey)}','preset',this.value)">${opts}</select></div>`;

          if (p.hasDateRange) {
            const showDates = curPreset === 'CUSTOM' ? '' : 'style="display:none"';
            html += `<div class="filter-sub" id="${dtId}-dates" ${showDates}><div class="sub-row">
              <label>From</label>
              <input type="date" value="${attr(cfg.date1||'')}" onchange="updateMsDatetime(${idx},'${attr(stepKey)}','${attr(paramKey)}','date1',this.value)">
              <span class="to">to</span>
              <input type="date" value="${attr(cfg.date2||'')}" onchange="updateMsDatetime(${idx},'${attr(stepKey)}','${attr(paramKey)}','date2',this.value)">
            </div></div>`;
          }

          if (p.hasTimeRange) {
            const allTime  = cfg.allTime || 1;
            const showTimes = allTime === 2 ? '' : 'style="display:none"';
            html += `<div class="filter-sub"><div class="sub-row"><label>Time</label>
              <select onchange="updateMsDatetime(${idx},'${attr(stepKey)}','${attr(paramKey)}','allTime',parseInt(this.value));
                document.getElementById('${dtId}-times').style.display=this.value==='2'?'':'none'">
                <option value="1" ${allTime===1?'selected':''}>All Day</option>
                <option value="2" ${allTime===2?'selected':''}>Custom</option>
              </select></div>
              <div class="sub-row" id="${dtId}-times" ${showTimes}>
                <label>From</label>
                <input type="time" step="1" value="${attr(cfg.time1||'')}" onchange="updateMsDatetime(${idx},'${attr(stepKey)}','${attr(paramKey)}','time1',this.value)">
                <span class="to">to</span>
                <input type="time" step="1" value="${attr(cfg.time2||'')}" onchange="updateMsDatetime(${idx},'${attr(stepKey)}','${attr(paramKey)}','time2',this.value)">
              </div></div>`;
          }

          {
            const preset      = curPreset;
            const showDays    = (preset !== 'THISDAY' && preset !== 'LASTDAY' && preset !== '');
            const hideDays    = !showDays ? 'style="display:none"' : '';
            const savedAllDay = cfg.allDayChecked || (p.allDayChecked || 'true');
            const savedDays   = cfg.days || (p.days || {});
            const showDayPick = savedAllDay === 'false' ? '' : 'style="display:none"';
            const dayDefs     = [['mon','Mon'],['tue','Tue'],['wed','Wed'],['thu','Thu'],['fri','Fri'],['sat','Sat'],['sun','Sun']];
            const btnHtml     = dayDefs.map(([d,lbl]) => {
              const act = (savedDays[d] === 'checked' || savedDays[d] === undefined) ? ' active' : '';
              return `<button type="button" class="day-btn${act}" data-day="${d}"
                onclick="toggleDayBtn(${idx},'${attr(stepKey)}','${attr(paramKey)}','${dtId}','${d}',this)">${lbl}</button>`;
            }).join('');
            html += `<div class="filter-sub" id="${dtId}-days" ${hideDays}><div class="sub-row"><label>Days</label>
              <select onchange="updateMsDatetime(${idx},'${attr(stepKey)}','${attr(paramKey)}','allDayChecked',this.value);
                document.getElementById('${dtId}-daypick').style.display=this.value==='false'?'':'none'">
                <option value="true"  ${savedAllDay!=='false'?'selected':''}>All Days</option>
                <option value="false" ${savedAllDay==='false'?'selected':''}>Custom</option>
              </select></div>
              <div class="sub-row" id="${dtId}-daypick" ${showDayPick}>
                <label>Select</label><div class="day-btns">${btnHtml}</div>
              </div></div>`;
          }

        } else if (p.type === 'cuic_field_filter') {
          const fields   = p.availableFields || [];
          let selectedConfigs = normalizeFieldFilterConfigs(savedVal, fields);
          if (selectedConfigs.length === 0 && savedVal === undefined && p.selectedFields?.length) {
            selectedConfigs = normalizeFieldFilterConfigs(p.selectedFields, fields);
          } else if (selectedConfigs.length === 0 && savedVal === undefined && p.selectedFieldIds?.length) {
            selectedConfigs = normalizeFieldFilterConfigs(p.selectedFieldIds, fields);
          }
          const ffId  = 'ff-' + idx + '-s' + step.step + '-' + paramKey.replace(/[^a-zA-Z0-9]/g,'_');
          const badge = `<span class="vl-badge">${fields.length} fields</span>`;

          html += `<div class="filter-field"><label title="${attr(paramKey)}">${esc(label)} ${badge}</label>
            <span id="${ffId}-selcount" style="font-size:12px;color:${selectedConfigs.length>0?'var(--green)':'var(--muted)'}">${selectedConfigs.length} selected</span></div>`;

          html += `<div class="ff-selected-list" id="${ffId}-selected" data-ridx="${idx}" data-stepkey="${attr(stepKey)}" data-pn="${attr(paramKey)}">`;
          if (selectedConfigs.length > 0) {
            selectedConfigs.forEach(cfg => {
              const field  = fields.find(f => (f.fieldId||f.label) === cfg.id);
              if (!field) return;
              const op = cfg.operator||'', v1 = cfg.value1||'', v2 = cfg.value2||'';
              html += _ffSelectedItemHtml(idx, stepKey, paramKey, cfg.id, field.label||cfg.id, op, v1, v2, false);
            });
          } else {
            html += '<p class="ff-empty-msg">No fields selected. Choose fields below to add criteria.</p>';
          }
          html += `</div>`;

          html += `<div class="ff-section" id="${ffId}-section"><div class="ff-toolbar">
            <input type="text" id="${ffId}-search" placeholder="\uD83D\uDD0D Filter fields..." oninput="filterFfChecklist('${ffId}',this.value)">
            <button onclick="ffMsCheckAll(${idx},'${attr(stepKey)}','${attr(paramKey)}','${ffId}')">\u2611 All</button>
            <button onclick="ffMsUncheckAll(${idx},'${attr(stepKey)}','${attr(paramKey)}','${ffId}')">\u2610 None</button>
          </div><div class="ff-checklist" id="${ffId}-list" onchange="ffToggleItem(${idx},'${attr(stepKey)}','${attr(paramKey)}','${ffId}',event)">`;
          fields.forEach(f => {
            const fid     = f.fieldId || f.label;
            const checked = selectedConfigs.some(c => c.id === fid) ? 'checked' : '';
            html += `<label data-name="${attr((f.combined||f.label||'').toLowerCase())}" data-label="${attr(f.label)}">
              <input type="checkbox" value="${attr(fid)}" ${checked}>
              <span>${esc(f.label)}</span><span class="ff-field-id">${esc(f.fieldId)}</span></label>`;
          });
          html += `</div></div>`;

        } else if (p.type === 'cuic_valuelist') {
          const isAll     = savedVal === 'all';
          const isSpec    = Array.isArray(savedVal);
          const selNames  = isSpec ? savedVal : (savedVal === undefined && p.selectedValues?.length ? p.selectedValues : []);
          const allNames  = p.availableNames || [];
          const vlId      = 'vl-' + idx + '-s' + step.step + '-' + paramKey.replace(/[^a-zA-Z0-9]/g,'_');
          const selCount  = isAll ? allNames.length : selNames.length;
          const badge     = `<span class="vl-badge">${allNames.length} available</span>`;

          html += `<div class="filter-field"><label title="${attr(paramKey)}">${esc(label)} ${badge}</label>
            <span id="${vlId}-selcount" style="font-size:12px;color:${selCount>0?'var(--green)':'var(--muted)'}">${selCount} selected</span></div>`;

          html += `<div class="vl-selected-summary" id="${vlId}-summary" data-type="vl-ms" data-ridx="${idx}" data-stepkey="${attr(stepKey)}" data-pn="${attr(paramKey)}" data-baseid="${vlId}">`;
          const showNames = isAll ? allNames : selNames;
          if (showNames.length > 0) {
            html += `<span class="vl-sel-label">\u2705 Selected:</span>`;
            showNames.slice(0, 20).forEach(n => {
              html += `<span class="vl-sel-tag">${esc(n)}<span class="vl-sel-x" onclick="deselectAndRefresh('${vlId}','${attr(n)}')">&times;</span></span>`;
            });
            if (showNames.length > 20) html += `<span class="vl-sel-more">+${showNames.length - 20} more</span>`;
          }
          html += `</div>`;

          const groups = p.availableGroups || [];
          html += `<div class="vl-section" id="${vlId}-section">`;
          if (groups.length) {
            html += `<div class="vl-groups" id="${vlId}-groups">`;
            groups.forEach((g, gi) => {
              const allC = g.members?.length > 0 && g.members.every(m => isAll || selNames.includes(m));
              html += `<button class="vl-group-btn${allC?' active':''}" data-gidx="${gi}"
                onclick="vlMsToggleGroup(${idx},'${attr(stepKey)}','${attr(paramKey)}','${vlId}',${gi})">
                ${esc(g.name)} <span class="vl-g-count">(${g.count})</span></button>`;
            });
            html += `</div>`;
          }
          html += `<div class="vl-toolbar">
            <input type="text" id="${vlId}-search" placeholder="\uD83D\uDD0D Filter names..." oninput="filterVlChecklist('${vlId}',this.value)">
            <button onclick="vlMsCheckAll(${idx},'${attr(stepKey)}','${attr(paramKey)}','${vlId}')">\u2611 All</button>
            <button onclick="vlMsUncheckAll(${idx},'${attr(stepKey)}','${attr(paramKey)}','${vlId}')">\u2610 None</button>
            <span class="vl-count" id="${vlId}-count">${selCount} / ${allNames.length}</span>
          </div><div class="vl-checklist" id="${vlId}-list">`;
          allNames.forEach(n => {
            const checked  = isAll || selNames.includes(n) ? 'checked' : '';
            const memberOf = groups.filter(g => (g.members||[]).includes(n)).map(g => g.name).join(',');
            html += `<label data-name="${attr(n.toLowerCase())}" data-groups="${attr(memberOf)}">
              <input type="checkbox" value="${attr(n)}" ${checked}
                onchange="vlMsToggleItem(${idx},'${attr(stepKey)}','${attr(paramKey)}','${vlId}')">
              <span>${esc(n)}</span></label>`;
          });
          html += `</div></div>`;

        } else if (p.type === 'checkbox') {
          const checked = savedVal !== undefined ? savedVal : (p.currentValue || false);
          html += `<div class="filter-field"><label title="${attr(paramKey)}">${esc(label)}</label>
            <input type="checkbox" ${checked?'checked':''} style="width:auto;"
              onchange="updateMsFilter(${idx},'${attr(stepKey)}','${attr(paramKey)}',this.checked)"></div>`;
        } else {
          const val = savedVal !== undefined ? savedVal : (p.currentValue || '');
          html += `<div class="filter-field"><label title="${attr(paramKey)}">${esc(label)}</label>
            <input type="${p.type==='number'?'number':'text'}" value="${attr(String(val))}"
              onchange="updateMsFilter(${idx},'${attr(stepKey)}','${attr(paramKey)}',this.value)"></div>`;
        }
      });
      html += `</div>`;
    });
    html += '</div></details>';
    return html;
  }

  if (isCuic) {
    const params = meta.params || [];
    params.forEach(p => {
      const paramKey = getCuicParamKey(p);
      const label = p.label || p.paramName || paramKey;
      const savedVal = getCuicSavedValue(filters, p);

      if (p.type === 'cuic_datetime') {
        const cfg       = typeof savedVal === 'string' ? {preset:savedVal} : (savedVal && typeof savedVal === 'object' ? savedVal : {});
        const curPreset = cfg.preset || '';
        const presets   = p.datePresets || [];
        let opts = `<option value="" ${!curPreset?'selected':''}>\u2014 use default \u2014</option>`;
        opts += presets.map(o => `<option value="${attr(o.value)}"${curPreset===o.value?' selected':''}>${esc(o.label)}</option>`).join('');
        const dtId = 'dt-' + idx + '-' + paramKey.replace(/[^a-zA-Z0-9]/g,'_');

        html += `<div class="filter-field"><label title="${attr(paramKey)}">${esc(label)}</label>
          <select id="${dtId}-preset" onchange="updateCuicDatetime(${idx},'${attr(paramKey)}','preset',this.value)">${opts}</select></div>`;

        if (p.hasDateRange) {
          const showDates = curPreset === 'CUSTOM' ? '' : 'style="display:none"';
          html += `<div class="filter-sub" id="${dtId}-dates" ${showDates}><div class="sub-row">
            <label>From</label>
            <input type="date" value="${attr(cfg.date1||'')}" onchange="updateCuicDatetime(${idx},'${attr(paramKey)}','date1',this.value)">
            <span class="to">to</span>
            <input type="date" value="${attr(cfg.date2||'')}" onchange="updateCuicDatetime(${idx},'${attr(paramKey)}','date2',this.value)">
          </div></div>`;
        }

        if (p.hasTimeRange) {
          const allTime   = cfg.allTime || 1;
          const showTimes = allTime === 2 ? '' : 'style="display:none"';
          html += `<div class="filter-sub"><div class="sub-row"><label>Time</label>
            <select onchange="updateCuicDatetime(${idx},'${attr(paramKey)}','allTime',parseInt(this.value));
              document.getElementById('${dtId}-times').style.display=this.value==='2'?'':'none'">
              <option value="1" ${allTime===1?'selected':''}>All Day</option>
              <option value="2" ${allTime===2?'selected':''}>Custom</option>
            </select></div>
            <div class="sub-row" id="${dtId}-times" ${showTimes}>
              <label>From</label>
              <input type="time" step="1" value="${attr(cfg.time1||'')}" onchange="updateCuicDatetime(${idx},'${attr(paramKey)}','time1',this.value)">
              <span class="to">to</span>
              <input type="time" step="1" value="${attr(cfg.time2||'')}" onchange="updateCuicDatetime(${idx},'${attr(paramKey)}','time2',this.value)">
            </div></div>`;
        }

      } else if (p.type === 'cuic_field_filter') {
        const fields    = p.availableFields || [];
        const selectedConfigs = normalizeFieldFilterConfigs(
          savedVal !== undefined ? savedVal : (p.selectedFields?.length ? p.selectedFields : p.selectedFieldIds),
          fields
        );
        const selIds    = selectedConfigs.map(cfg => cfg.id);
        const ffId      = 'ff-' + idx + '-' + paramKey.replace(/[^a-zA-Z0-9]/g,'_');
        const selCount  = selIds.length;
        const badge     = `<span class="vl-badge">${fields.length} fields</span>`;
        const labelMap  = {};
        fields.forEach(f => { labelMap[f.fieldId||f.label] = f.label; });

        html += `<div class="filter-field"><label title="${attr(paramKey)}">${esc(label)} ${badge}</label>
          <span id="${ffId}-selcount" style="font-size:12px;color:${selCount>0?'var(--green)':'var(--muted)'}">${selCount} selected</span></div>`;

        html += `<div class="vl-selected-summary" id="${ffId}-summary" data-type="ff" data-ridx="${idx}" data-pn="${attr(paramKey)}" data-baseid="${ffId}"
          data-labelmap='${JSON.stringify(labelMap).replace(/'/g,"&#39;")}'>`;
        const showFields = fields.filter(f => selIds.includes(f.fieldId||f.label));
        if (showFields.length > 0) {
          html += `<span class="vl-sel-label">\u2705 Selected:</span>`;
          showFields.slice(0,20).forEach(f => {
            const fid = f.fieldId||f.label;
            html += `<span class="vl-sel-tag">${esc(f.label)}<span class="vl-sel-x" onclick="deselectAndRefresh('${ffId}','${attr(fid)}')">&times;</span></span>`;
          });
          if (showFields.length > 20) html += `<span class="vl-sel-more">+${showFields.length-20} more</span>`;
        }
        html += `</div>`;

        html += `<div class="ff-section" id="${ffId}-section"><div class="ff-toolbar">
          <input type="text" id="${ffId}-search" placeholder="\uD83D\uDD0D Filter fields..." oninput="filterFfChecklist('${ffId}',this.value)">
          <button onclick="ffCheckAll(${idx},'${attr(paramKey)}','${ffId}')">\u2611 All</button>
          <button onclick="ffUncheckAll(${idx},'${attr(paramKey)}','${ffId}')">\u2610 None</button>
          <span class="ff-count" id="${ffId}-count">${selCount} / ${fields.length}</span>
        </div><div class="ff-checklist" id="${ffId}-list">`;
        fields.forEach(f => {
          const fid     = f.fieldId||f.label;
          const checked = selIds.includes(fid) ? 'checked' : '';
          html += `<label data-name="${attr((f.combined||f.label||'').toLowerCase())}" data-label="${attr(f.label)}">
            <input type="checkbox" value="${attr(fid)}" ${checked} onchange="ffSpabToggleItem(${idx},'${attr(paramKey)}','${ffId}')">
            <span>${esc(f.label)}</span><span class="ff-field-id">${esc(f.fieldId)}</span></label>`;
        });
        html += `</div></div>`;

      } else if (p.type === 'cuic_valuelist') {
        const isAll    = savedVal === 'all';
        const isSpec   = Array.isArray(savedVal);
        const selNames = isSpec ? savedVal : (savedVal === undefined && p.selectedValues?.length ? p.selectedValues : []);
        const allNames = p.availableNames || [];
        const vlId     = 'vl-' + idx + '-' + paramKey.replace(/[^a-zA-Z0-9]/g,'_');
        const selCount = isAll ? allNames.length : selNames.length;
        const badge    = `<span class="vl-badge">${allNames.length} available</span>`;

        html += `<div class="filter-field"><label title="${attr(paramKey)}">${esc(label)} ${badge}</label>
          <span id="${vlId}-selcount" style="font-size:12px;color:${selCount>0?'var(--green)':'var(--muted)'}">${selCount} selected</span></div>`;

        html += `<div class="vl-selected-summary" id="${vlId}-summary" data-type="vl" data-ridx="${idx}" data-pn="${attr(paramKey)}" data-baseid="${vlId}">`;
        const showNamesSp = isAll ? allNames : selNames;
        if (showNamesSp.length > 0) {
          html += `<span class="vl-sel-label">\u2705 Selected:</span>`;
          showNamesSp.slice(0,20).forEach(n => {
            html += `<span class="vl-sel-tag">${esc(n)}<span class="vl-sel-x" onclick="deselectAndRefresh('${vlId}','${attr(n)}')">&times;</span></span>`;
          });
          if (showNamesSp.length > 20) html += `<span class="vl-sel-more">+${showNamesSp.length-20} more</span>`;
        }
        html += `</div>`;

        const groups = p.availableGroups || [];
        html += `<div class="vl-section" id="${vlId}-section">`;
        if (groups.length) {
          html += `<div class="vl-groups" id="${vlId}-groups">`;
          groups.forEach((g, gi) => {
            const allC = g.members?.length > 0 && g.members.every(m => isAll || selNames.includes(m));
            html += `<button class="vl-group-btn${allC?' active':''}" data-gidx="${gi}"
              onclick="vlToggleGroup(${idx},'${attr(paramKey)}','${vlId}',${gi})">
              ${esc(g.name)} <span class="vl-g-count">(${g.count})</span></button>`;
          });
          html += `</div>`;
        }
        html += `<div class="vl-toolbar">
          <input type="text" id="${vlId}-search" placeholder="\uD83D\uDD0D Filter names..." oninput="filterVlChecklist('${vlId}',this.value)">
          <button onclick="vlCheckAll(${idx},'${attr(paramKey)}','${vlId}')">\u2611 All</button>
          <button onclick="vlUncheckAll(${idx},'${attr(paramKey)}','${vlId}')">\u2610 None</button>
          <span class="vl-count" id="${vlId}-count">${selCount} / ${allNames.length}</span>
        </div><div class="vl-checklist" id="${vlId}-list">`;
        allNames.forEach(n => {
          const checked  = isAll || selNames.includes(n) ? 'checked' : '';
          const memberOf = groups.filter(g => (g.members||[]).includes(n)).map(g => g.name).join(',');
          html += `<label data-name="${attr(n.toLowerCase())}" data-groups="${attr(memberOf)}">
            <input type="checkbox" value="${attr(n)}" ${checked} onchange="vlToggleItem(${idx},'${attr(paramKey)}','${vlId}')">
            <span>${esc(n)}</span></label>`;
        });
        html += `</div></div>`;

      } else if (p.type === 'checkbox') {
        const checked = savedVal !== undefined ? savedVal : (p.currentValue || false);
        html += `<div class="filter-field"><label title="${attr(paramKey)}">${esc(label)}</label>
          <input type="checkbox" ${checked?'checked':''} style="width:auto;"
            onchange="updateCuicFilter(${idx},'${attr(paramKey)}',this.checked)"></div>`;
      } else {
        const val = savedVal !== undefined ? savedVal : (p.currentValue || '');
        html += `<div class="filter-field"><label title="${attr(paramKey)}">${esc(label)}</label>
          <input type="${p.type==='number'?'number':'text'}" value="${attr(String(val))}"
            onchange="updateCuicFilter(${idx},'${attr(paramKey)}',this.value)"></div>`;
      }
    });
    html += '</div>';
    return html;
  }

  // ── Generic step-based wizard ──
  (meta.steps || []).forEach(step => {
    const stepKey   = 'step_' + step.step;
    const savedStep = filters[stepKey] || {};
    html += `<div class="filter-step"><div class="step-label">Step ${step.step}</div>`;
    (step.fields || []).forEach(field => {
      const key = field.id || field.name || field.label || '';
      if (!key) return;
      const savedVal     = savedStep[key];
      const displayLabel = field.label || field.name || field.id;
      if (field.type === 'select') {
        let opts = (field.options || []).map(o => {
          const sel = savedVal !== undefined ? (Array.isArray(savedVal) ? savedVal.includes(o.value) : savedVal === o.value) : o.selected;
          return `<option value="${attr(o.value)}"${sel?' selected':''}>${esc(o.text)}</option>`;
        }).join('');
        html += `<div class="filter-field"><label title="${attr(key)}">${esc(displayLabel)}</label>
          <select ${field.multiple?'multiple':''} onchange="updateFilterValue(${idx},'${stepKey}','${attr(key)}',this)">${opts}</select></div>`;
      } else if (field.type === 'checkbox') {
        const checked = savedVal !== undefined ? savedVal : field.value;
        html += `<div class="filter-field"><label title="${attr(key)}">${esc(displayLabel)}</label>
          <input type="checkbox" ${checked?'checked':''} style="width:auto;"
            onchange="updateFilterValue(${idx},'${stepKey}','${attr(key)}',this)"></div>`;
      } else {
        const val = savedVal !== undefined ? savedVal : (field.value || '');
        html += `<div class="filter-field"><label title="${attr(key)}">${esc(displayLabel)}</label>
          <input type="${field.inputType||'text'}" value="${attr(String(val))}"
            onchange="updateFilterValue(${idx},'${stepKey}','${attr(key)}',this)"></div>`;
      }
    });
    html += '</div>';
  });
  html += '</div></details>';
  return html;
}

// ── Helper: build HTML for a ff-selected-item ────────────────────────────
function _ffSelectedItemHtml(ridx, stepKey, pn, fid, fLabel, op, v1, v2, isSpab) {
  const rm = isSpab
    ? `ffSpabToggleItem` // handled via checkbox uncheck
    : `ffRemoveField(${ridx},'${attr(stepKey)}','${attr(pn)}','${attr(fid)}')`;
  const rmBtn = isSpab ? '' : `<button class="ff-si-remove" onclick="${rm}">×</button>`;
  const upd = isSpab
    ? `ffSpabToggleItem(${ridx},'${attr(pn)}','ff-${ridx}-${pn.replace(/[^a-zA-Z0-9]/g,'_')}')`
    : `ffUpdateField(${ridx},'${attr(stepKey)}','${attr(pn)}','${attr(fid)}','operator',this.value)`;
  return `<div class="ff-selected-item" data-fid="${attr(fid)}">
    <div class="ff-si-header">
      <span class="ff-si-label">${esc(fLabel)}</span>
      <span class="ff-si-fid">(${esc(fid)})</span>
      ${rmBtn}
    </div>
    <div class="ff-si-criteria">
      <div><label>Operator:</label>
        <select onchange="${upd}">
          <option value="">— select —</option>
          <option value="EQ"${op==='EQ'?' selected':''}>Equal to</option>
          <option value="NEQ"${op==='NEQ'||op==='NE'?' selected':''}>Not equal to</option>
          <option value="G"${op==='G'||op==='GT'?' selected':''}>Greater than</option>
          <option value="GEQ"${op==='GEQ'||op==='GE'?' selected':''}>Greater or equal</option>
          <option value="L"${op==='L'||op==='LT'?' selected':''}>Less than</option>
          <option value="LEQ"${op==='LEQ'||op==='LE'?' selected':''}>Less or equal</option>
          <option value="BTWN"${op==='BTWN'||op==='BW'?' selected':''}>Between</option>
        </select>
      </div>
      <div><label>Value:</label>
        <input type="text" value="${attr(v1)}" placeholder="Value"
          onchange="ffUpdateField(${ridx},'${attr(stepKey)}','${attr(pn)}','${attr(fid)}','value1',this.value)">
      </div>
      ${op==='BTWN'||op==='BW'?`<div><label>To:</label>
        <input type="text" value="${attr(v2)}" placeholder="Upper bound"
          onchange="ffUpdateField(${ridx},'${attr(stepKey)}','${attr(pn)}','${attr(fid)}','value2',this.value)">
      </div>`:''}
    </div>
  </div>`;
}

// ══════════════════════════════════════════════════════════════════════════
//  FILTER DATA MODEL HELPERS
// ══════════════════════════════════════════════════════════════════════════

function updateCuicFilter(reportIdx, paramName, value) {
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  if (value === '' || value === undefined) delete r.filters[paramName];
  else r.filters[paramName] = value;
  markDirty();
}

function updateCuicDatetime(reportIdx, paramName, field, value) {
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  let cur = r.filters[paramName];
  if (typeof cur === 'string') cur = {preset: cur};
  if (!cur || typeof cur !== 'object') cur = {};
  cur[field] = value;
  if (field === 'preset') {
    const dtId = 'dt-' + reportIdx + '-' + paramName.replace(/[^a-zA-Z0-9]/g,'_');
    const el = document.getElementById(dtId + '-dates');
    if (el) el.style.display = value === 'CUSTOM' ? '' : 'none';
  }
  const keys = Object.keys(cur).filter(k => cur[k] !== undefined && cur[k] !== '');
  if (keys.length === 1 && keys[0] === 'preset' && cur.preset !== 'CUSTOM') {
    r.filters[paramName] = cur.preset || undefined;
    if (!cur.preset) delete r.filters[paramName];
  } else {
    r.filters[paramName] = cur;
  }
  markDirty();
}

function vlToggleItem(reportIdx, paramName, vlId) {
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  const listEl = document.getElementById(vlId + '-list');
  if (!listEl) return;
  const checked = Array.from(listEl.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value);
  const total   = listEl.querySelectorAll('input[type=checkbox]').length;
  r.filters[paramName] = checked.length === total ? 'all' : checked;
  const ce = document.getElementById(vlId + '-count');
  if (ce) ce.textContent = checked.length + ' / ' + total;
  vlUpdateGroupButtons(vlId, reportIdx, paramName);
  _refreshSummaryTags(vlId);
  markDirty();
}

function vlCheckAll(reportIdx, paramName, vlId) {
  const listEl = document.getElementById(vlId + '-list');
  if (!listEl) return;
  listEl.querySelectorAll('label').forEach(l => { if (l.style.display !== 'none') { const cb = l.querySelector('input'); if (cb) cb.checked = true; } });
  vlToggleItem(reportIdx, paramName, vlId);
}

function vlUncheckAll(reportIdx, paramName, vlId) {
  const listEl = document.getElementById(vlId + '-list');
  if (!listEl) return;
  listEl.querySelectorAll('label').forEach(l => { if (l.style.display !== 'none') { const cb = l.querySelector('input'); if (cb) cb.checked = false; } });
  vlToggleItem(reportIdx, paramName, vlId);
}

function filterVlChecklist(vlId, query) {
  const listEl = document.getElementById(vlId + '-list');
  if (!listEl) return;
  const q = (query || '').toLowerCase();
  listEl.querySelectorAll('label').forEach(l => { l.style.display = (!q || (l.getAttribute('data-name')||'').includes(q)) ? '' : 'none'; });
}

function vlToggleGroup(reportIdx, paramName, vlId, groupIdx) {
  const r    = cuicReports[reportIdx];
  const meta = r._wizard_meta || (r.filters && r.filters._meta) || {};
  const p    = (meta.params || []).find(pp => getCuicParamAliases(pp).includes(paramName));
  if (!p) return;
  const group = (p.availableGroups || [])[groupIdx];
  if (!group?.members) return;
  const listEl    = document.getElementById(vlId + '-list');
  if (!listEl) return;
  const memberSet = new Set(group.members);
  const cbs       = Array.from(listEl.querySelectorAll('input[type=checkbox]')).filter(cb => memberSet.has(cb.value));
  const allC      = cbs.every(cb => cb.checked);
  cbs.forEach(cb => cb.checked = !allC);
  vlToggleItem(reportIdx, paramName, vlId);
}

function vlUpdateGroupButtons(vlId, reportIdx, paramName) {
  const groupsEl = document.getElementById(vlId + '-groups');
  if (!groupsEl) return;
  const r    = cuicReports[reportIdx];
  const meta = r._wizard_meta || (r.filters && r.filters._meta) || {};
  const p    = (meta.params || []).find(pp => getCuicParamAliases(pp).includes(paramName));
  if (!p) return;
  const listEl    = document.getElementById(vlId + '-list');
  if (!listEl) return;
  const checkedV  = new Set(Array.from(listEl.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value));
  groupsEl.querySelectorAll('.vl-group-btn').forEach(btn => {
    const g = (p.availableGroups || [])[parseInt(btn.getAttribute('data-gidx'))];
    if (!g?.members) return;
    btn.classList.toggle('active', g.members.every(m => checkedV.has(m)));
  });
}

function _findMsParam(meta, stepKey, paramName) {
  const step = (meta.steps || []).find(s => s.step === parseInt(stepKey.replace('step_','')));
  if (!step) return null;
  return (step.params || []).find(p => getCuicParamAliases(p).includes(paramName)) || null;
}

function switchWizardTab(idx, tabIdx) {
  const tabs = document.getElementById('wst-' + idx);
  if (!tabs) return;
  tabs.querySelectorAll('.wst-tab').forEach((t, i) => t.classList.toggle('active', i === tabIdx));
  let si = 0, body;
  while ((body = document.getElementById('wsb-' + idx + '-' + si))) { body.classList.toggle('active', si === tabIdx); si++; }
}

function updateMsFilter(reportIdx, stepKey, paramName, value) {
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  if (!r.filters[stepKey]) r.filters[stepKey] = {};
  if (value === '' || value === undefined) delete r.filters[stepKey][paramName];
  else r.filters[stepKey][paramName] = value;
  markDirty();
}

function updateMsDatetime(reportIdx, stepKey, paramName, field, value) {
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  if (!r.filters[stepKey]) r.filters[stepKey] = {};
  let cur = r.filters[stepKey][paramName];
  if (typeof cur === 'string') cur = {preset: cur};
  if (!cur || typeof cur !== 'object') cur = {};
  cur[field] = value;
  if (field === 'preset') {
    const sn   = stepKey.replace('step_','');
    const dtId = 'dt-' + reportIdx + '-s' + sn + '-' + paramName.replace(/[^a-zA-Z0-9]/g,'_');
    const de   = document.getElementById(dtId + '-dates');
    if (de) de.style.display = value === 'CUSTOM' ? '' : 'none';
    const dy   = document.getElementById(dtId + '-days');
    if (dy) dy.style.display = (value === 'THISDAY' || value === 'LASTDAY' || value === '') ? 'none' : '';
  }
  const keys = Object.keys(cur).filter(k => cur[k] !== undefined && cur[k] !== '');
  if (keys.length === 1 && keys[0] === 'preset' && cur.preset !== 'CUSTOM') {
    r.filters[stepKey][paramName] = cur.preset || undefined;
    if (!cur.preset) delete r.filters[stepKey][paramName];
  } else {
    r.filters[stepKey][paramName] = cur;
  }
  markDirty();
}

function toggleDayBtn(reportIdx, stepKey, paramName, dtId, day, btn) {
  btn.classList.toggle('active');
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  if (!r.filters[stepKey]) r.filters[stepKey] = {};
  let cur = r.filters[stepKey][paramName];
  if (typeof cur === 'string') cur = {preset: cur};
  if (!cur || typeof cur !== 'object') cur = {};
  if (!cur.days) cur.days = {};
  cur.days[day] = btn.classList.contains('active') ? 'checked' : '';
  r.filters[stepKey][paramName] = cur;
  markDirty();
}

function vlMsToggleItem(reportIdx, stepKey, paramName, vlId) {
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  if (!r.filters[stepKey]) r.filters[stepKey] = {};
  const listEl = document.getElementById(vlId + '-list');
  if (!listEl) return;
  const checked = Array.from(listEl.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value);
  const total   = listEl.querySelectorAll('input[type=checkbox]').length;
  r.filters[stepKey][paramName] = checked.length === total ? 'all' : checked;
  const ce = document.getElementById(vlId + '-count');
  if (ce) ce.textContent = checked.length + ' / ' + total;
  vlMsUpdateGroupButtons(vlId, reportIdx, stepKey, paramName);
  _refreshSummaryTags(vlId);
  markDirty();
}

function vlMsCheckAll(reportIdx, stepKey, paramName, vlId) {
  const listEl = document.getElementById(vlId + '-list');
  if (!listEl) return;
  listEl.querySelectorAll('label').forEach(l => { if (l.style.display !== 'none') { const cb = l.querySelector('input'); if (cb) cb.checked = true; } });
  vlMsToggleItem(reportIdx, stepKey, paramName, vlId);
}

function vlMsUncheckAll(reportIdx, stepKey, paramName, vlId) {
  const listEl = document.getElementById(vlId + '-list');
  if (!listEl) return;
  listEl.querySelectorAll('label').forEach(l => { if (l.style.display !== 'none') { const cb = l.querySelector('input'); if (cb) cb.checked = false; } });
  vlMsToggleItem(reportIdx, stepKey, paramName, vlId);
}

function vlMsToggleGroup(reportIdx, stepKey, paramName, vlId, groupIdx) {
  const r     = cuicReports[reportIdx];
  const meta  = r._wizard_meta || (r.filters && r.filters._meta) || {};
  const p     = _findMsParam(meta, stepKey, paramName);
  if (!p) return;
  const group = (p.availableGroups || [])[groupIdx];
  if (!group?.members) return;
  const listEl    = document.getElementById(vlId + '-list');
  if (!listEl) return;
  const memberSet = new Set(group.members);
  const cbs       = Array.from(listEl.querySelectorAll('input[type=checkbox]')).filter(cb => memberSet.has(cb.value));
  const allC      = cbs.every(cb => cb.checked);
  cbs.forEach(cb => cb.checked = !allC);
  vlMsToggleItem(reportIdx, stepKey, paramName, vlId);
}

function vlMsUpdateGroupButtons(vlId, reportIdx, stepKey, paramName) {
  const groupsEl = document.getElementById(vlId + '-groups');
  if (!groupsEl) return;
  const r    = cuicReports[reportIdx];
  const meta = r._wizard_meta || (r.filters && r.filters._meta) || {};
  const p    = _findMsParam(meta, stepKey, paramName);
  if (!p) return;
  const listEl   = document.getElementById(vlId + '-list');
  if (!listEl) return;
  const checkedV = new Set(Array.from(listEl.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value));
  groupsEl.querySelectorAll('.vl-group-btn').forEach(btn => {
    const g = (p.availableGroups || [])[parseInt(btn.getAttribute('data-gidx'))];
    if (!g?.members) return;
    btn.classList.toggle('active', g.members.every(m => checkedV.has(m)));
  });
}

function deselectAndRefresh(baseId, value) {
  const listEl = document.getElementById(baseId + '-list');
  if (listEl) {
    const cb = listEl.querySelector(`input[type=checkbox][value="${CSS.escape(value)}"]`);
    if (cb) { cb.checked = false; cb.dispatchEvent(new Event('change', {bubbles: true})); }
  }
}

function _refreshSummaryTags(baseId) {
  const summaryEl  = document.getElementById(baseId + '-summary');
  const selcountEl = document.getElementById(baseId + '-selcount');
  const listEl     = document.getElementById(baseId + '-list');
  if (!summaryEl || !listEl) return;
  const checkedVals = Array.from(listEl.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value);
  let labelMap = null;
  try { labelMap = JSON.parse(summaryEl.getAttribute('data-labelmap') || 'null'); } catch(e) {}
  let html = '';
  if (checkedVals.length > 0) {
    html += `<span class="vl-sel-label">\u2705 Selected:</span>`;
    checkedVals.slice(0,20).forEach(v => {
      const dl = (labelMap && labelMap[v]) ? labelMap[v] : v;
      html += `<span class="vl-sel-tag">${esc(dl)}<span class="vl-sel-x" onclick="deselectAndRefresh('${baseId}','${attr(v)}')">&times;</span></span>`;
    });
    if (checkedVals.length > 20) html += `<span class="vl-sel-more">+${checkedVals.length-20} more</span>`;
  }
  summaryEl.innerHTML = html;
  if (selcountEl) {
    selcountEl.textContent = checkedVals.length + ' selected';
    selcountEl.style.color = checkedVals.length > 0 ? 'var(--green)' : 'var(--muted)';
  }
}

function ffToggleItem(reportIdx, stepKey, paramName, ffId, event) {
  if (!event?.target) return;
  const cb = event.target;
  if (cb.tagName !== 'INPUT' || cb.type !== 'checkbox') return;
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  if (!r.filters[stepKey]) r.filters[stepKey] = {};
  let configs = r.filters[stepKey][paramName] || [];
  if (!Array.isArray(configs)) configs = [];
  configs = configs.map(c => typeof c === 'string' ? {id:c} : c);
  if (cb.checked) { if (!configs.find(c => c.id === cb.value)) configs.push({id:cb.value, operator:'', value1:''}); }
  else configs = configs.filter(c => c.id !== cb.value);
  r.filters[stepKey][paramName] = configs;
  _refreshFieldFilterSelected(reportIdx, stepKey, paramName, ffId);
  markDirty();
}

function ffMsCheckAll(reportIdx, stepKey, paramName, ffId) {
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  if (!r.filters[stepKey]) r.filters[stepKey] = {};
  let configs = r.filters[stepKey][paramName] || [];
  if (!Array.isArray(configs)) configs = [];
  configs = configs.map(c => typeof c === 'string' ? {id:c} : c);
  const listEl = document.getElementById(ffId + '-list');
  if (!listEl) return;
  listEl.querySelectorAll('label').forEach(l => {
    if (l.style.display !== 'none') {
      const cb = l.querySelector('input[type=checkbox]');
      if (cb && !cb.checked) { cb.checked = true; if (!configs.find(c => c.id === cb.value)) configs.push({id:cb.value, operator:'', value1:''}); }
    }
  });
  r.filters[stepKey][paramName] = configs;
  _refreshFieldFilterSelected(reportIdx, stepKey, paramName, ffId);
  markDirty();
}

function ffMsUncheckAll(reportIdx, stepKey, paramName, ffId) {
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  if (!r.filters[stepKey]) r.filters[stepKey] = {};
  let configs = (r.filters[stepKey][paramName] || []).map(c => typeof c === 'string' ? {id:c} : c);
  const listEl = document.getElementById(ffId + '-list');
  if (!listEl) return;
  const visIds = [];
  listEl.querySelectorAll('label').forEach(l => {
    if (l.style.display !== 'none') { const cb = l.querySelector('input[type=checkbox]'); if (cb) { cb.checked = false; visIds.push(cb.value); } }
  });
  r.filters[stepKey][paramName] = configs.filter(c => !visIds.includes(c.id));
  _refreshFieldFilterSelected(reportIdx, stepKey, paramName, ffId);
  markDirty();
}

function ffRemoveField(reportIdx, stepKey, paramName, fieldId) {
  const r = cuicReports[reportIdx];
  if (!r.filters?.[stepKey]) return;
  let configs = (r.filters[stepKey][paramName] || []).map(c => typeof c === 'string' ? {id:c} : c);
  r.filters[stepKey][paramName] = configs.filter(c => c.id !== fieldId);
  const ffId  = `ff-${reportIdx}-s${stepKey.replace('step_','')}-${paramName.replace(/[^a-zA-Z0-9]/g,'_')}`;
  const listEl = document.getElementById(ffId + '-list');
  if (listEl) { const cb = listEl.querySelector(`input[value="${fieldId}"]`); if (cb) cb.checked = false; }
  _refreshFieldFilterSelected(reportIdx, stepKey, paramName, ffId);
  markDirty();
}

function ffUpdateField(reportIdx, stepKey, paramName, fieldId, prop, val) {
  const r = cuicReports[reportIdx];
  if (!r.filters?.[stepKey]) return;
  let configs = (r.filters[stepKey][paramName] || []).map(c => typeof c === 'string' ? {id:c} : c);
  const cfg = configs.find(c => c.id === fieldId);
  if (cfg) {
    cfg[prop] = val;
    r.filters[stepKey][paramName] = configs;
    if (prop === 'operator') {
      const ffId = `ff-${reportIdx}-s${stepKey.replace('step_','')}-${paramName.replace(/[^a-zA-Z0-9]/g,'_')}`;
      _refreshFieldFilterSelected(reportIdx, stepKey, paramName, ffId);
    }
    markDirty();
  }
}

function _refreshFieldFilterSelected(reportIdx, stepKey, paramName, ffId) {
  const r       = cuicReports[reportIdx];
  const configs = ((r.filters?.[stepKey]?.[paramName]) || []).map(c => typeof c === 'string' ? {id:c} : c);

  const ce = document.getElementById(ffId + '-selcount');
  if (ce) { ce.textContent = configs.length + ' selected'; ce.style.color = configs.length > 0 ? 'var(--green)' : 'var(--muted)'; }

  const selDiv = document.getElementById(ffId + '-selected');
  if (!selDiv) return;

  const meta    = r._wizard_meta || (r.filters && r.filters._meta) || {};
  const stepNum = parseInt((selDiv.dataset.stepkey || stepKey).replace('step_',''));
  const step    = (meta.steps || []).find(s => s.step === stepNum);
  const param   = step?.params?.find(p => p.paramName === (selDiv.dataset.pn || paramName));
  const fields  = param?.availableFields || [];

  let html = '';
  if (configs.length > 0) {
    configs.forEach(cfg => {
      const field  = fields.find(f => (f.fieldId||f.label) === cfg.id);
      const fLabel = field?.label || cfg.id;
      const op = cfg.operator||'', v1 = cfg.value1||'', v2 = cfg.value2||'';
      html += _ffSelectedItemHtml(reportIdx, stepKey, paramName, cfg.id, fLabel, op, v1, v2, false);
    });
  } else {
    html = '<p class="ff-empty-msg">No fields selected. Choose fields below to add criteria.</p>';
  }
  selDiv.innerHTML = html;
}

function ffSpabToggleItem(reportIdx, paramName, ffId) {
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  const listEl = document.getElementById(ffId + '-list');
  if (!listEl) return;
  const checked = Array.from(listEl.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value);
  const total   = listEl.querySelectorAll('input[type=checkbox]').length;
  r.filters[paramName] = checked.length === total ? 'all' : checked;
  const ce = document.getElementById(ffId + '-count');
  if (ce) ce.textContent = checked.length + ' / ' + total;
  _refreshSummaryTags(ffId);
  markDirty();
}

function ffCheckAll(reportIdx, paramName, ffId) {
  const listEl = document.getElementById(ffId + '-list');
  if (!listEl) return;
  listEl.querySelectorAll('label').forEach(l => { if (l.style.display !== 'none') { const cb = l.querySelector('input'); if (cb) cb.checked = true; } });
  ffSpabToggleItem(reportIdx, paramName, ffId);
}

function ffUncheckAll(reportIdx, paramName, ffId) {
  const listEl = document.getElementById(ffId + '-list');
  if (!listEl) return;
  listEl.querySelectorAll('label').forEach(l => { if (l.style.display !== 'none') { const cb = l.querySelector('input'); if (cb) cb.checked = false; } });
  ffSpabToggleItem(reportIdx, paramName, ffId);
}

function filterFfChecklist(ffId, query) {
  const listEl = document.getElementById(ffId + '-list');
  if (!listEl) return;
  const q = (query || '').toLowerCase().trim();
  listEl.querySelectorAll('label').forEach(l => { l.style.display = (!q || (l.getAttribute('data-name')||'').includes(q)) ? '' : 'none'; });
}

function updateFilterValue(reportIdx, stepKey, fieldKey, el) {
  const r = cuicReports[reportIdx];
  if (!r.filters) r.filters = {};
  if (!r.filters[stepKey]) r.filters[stepKey] = {};
  if (el.type === 'checkbox') r.filters[stepKey][fieldKey] = el.checked;
  else if (el.tagName === 'SELECT' && el.multiple) r.filters[stepKey][fieldKey] = Array.from(el.selectedOptions).map(o => o.value);
  else r.filters[stepKey][fieldKey] = el.value;
  markDirty();
}

function clearFilters(reportIdx) {
  const r    = cuicReports[reportIdx];
  const meta = r._wizard_meta || (r.filters && r.filters._meta) || null;
  r.filters  = {};
  if (meta) r.filters._meta = meta;
  renderCuicReports();
  markDirty();
  showToast('Filters cleared for ' + (r.label || 'report'), 'info');
}

// ══════════════════════════════════════════════════════════════════════════
//  DISCOVER FILTERS
// ══════════════════════════════════════════════════════════════════════════

async function discoverFilters(reportIdx) {
  const r   = cuicReports[reportIdx];
  const btn = document.getElementById('discover-btn-' + reportIdx);
  const parsedPath = splitCuicReportPath(getCuicReportPath(r));

  if (!parsedPath.name) { showToast('Set the CUIC report path first', 'error'); return; }
  if (!parsedPath.folder) { showToast('Use the full CUIC report path, for example Folder/Report Name', 'error'); return; }

  r.folder = parsedPath.folder;
  r.name = parsedPath.name;

  const origHtml = btn.innerHTML;
  btn.innerHTML  = '<span class="spinner"></span> Discovering\u2026';
  btn.disabled   = true;
  showToast('Launching browser to discover wizard fields\u2026 This may take 30\u201360s.', 'info');

  try {
    const res  = await fetch('/api/discover-filters', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ folder: r.folder, name: r.name, path: parsedPath.path })
    });
    const data = await res.json();

    if (!res.ok || data.error) { showToast('Discovery error: ' + (data.error || 'Unknown validation error'), 'error'); return; }
    if (!data.steps || data.steps.length === 0) { showToast('No wizard steps found', 'error'); return; }

    const isCuic      = data.type === 'cuic_spab';
    const isMultiStep = data.type === 'cuic_multistep';

    if (isMultiStep) {
      const metaObj = { schemaVersion: data.schemaVersion || 2, type: 'cuic_multistep', steps: data.steps, stepTitles: data.stepTitles || data.steps.map(s => s.title || 'Step ' + s.step) };
      r._wizard_meta = metaObj;
      r.filters = { _meta: metaObj };
      let total = 0;
      data.steps.forEach(step => {
        const sk = 'step_' + step.step;
        r.filters[sk] = {};
        (step.params || []).forEach(p => {
          total++;
          const paramKey = getCuicParamKey(p);
          if (!paramKey) return;
          if (p.type === 'cuic_datetime' && p.currentPreset) r.filters[sk][paramKey] = p.currentPreset;
          if (p.type === 'cuic_valuelist' && p.selectedValues?.length) r.filters[sk][paramKey] = cloneCuicData(p.selectedValues);
          if (p.type === 'cuic_field_filter' && p.selectedFields?.length) {
            r.filters[sk][paramKey] = normalizeFieldFilterConfigs(p.selectedFields, p.availableFields);
          } else if (p.type === 'cuic_field_filter' && p.selectedFieldIds?.length) {
            r.filters[sk][paramKey] = normalizeFieldFilterConfigs(p.selectedFieldIds, p.availableFields);
          }
        });
      });
      // Store column metadata if discovered
      if (data._columns_meta && (data._columns_meta.available || []).length > 0) {
        r._columns_meta = data._columns_meta;
        showToast(`Discovered ${data.steps.length} wizard step(s) with ${total} parameter(s) and ${data._columns_meta.available.length} columns!`, 'success');
      } else {
        showToast(`Discovered ${data.steps.length} wizard step(s) with ${total} parameter(s)!`, 'success');
      }

    } else if (isCuic) {
      const metaObj = { schemaVersion: data.schemaVersion || 2, type: 'cuic_spab', params: data.params || [] };
      r._wizard_meta = metaObj;
      r.filters = { _meta: metaObj };
      (data.params || []).forEach(p => {
        const paramKey = getCuicParamKey(p);
        if (!paramKey) return;
        if (p.type === 'cuic_datetime' && p.currentPreset) r.filters[paramKey] = p.currentPreset;
        if (p.type === 'cuic_valuelist' && p.selectedValues?.length) r.filters[paramKey] = cloneCuicData(p.selectedValues);
        if (p.type === 'cuic_field_filter' && p.selectedFields?.length) {
          r.filters[paramKey] = normalizeFieldFilterConfigs(p.selectedFields, p.availableFields);
        }
      });
      if (data._columns_meta && (data._columns_meta.available || []).length > 0) {
        r._columns_meta = data._columns_meta;
        showToast(`Discovered ${(data.params||[]).length} CUIC parameter(s) and ${data._columns_meta.available.length} columns!`, 'success');
      } else {
        showToast(`Discovered ${(data.params||[]).length} CUIC parameter(s)!`, 'success');
      }

    } else {
      r._wizard_meta = { steps: data.steps };
      r.filters = { _meta: { steps: data.steps } };
      data.steps.forEach(step => {
        const sk = 'step_' + step.step;
        r.filters[sk] = {};
        (step.fields || []).forEach(field => { const key = field.id||field.name||field.label; if (key) r.filters[sk][key] = field.value; });
      });
      if (data._columns_meta && (data._columns_meta.available || []).length > 0) {
        r._columns_meta = data._columns_meta;
        showToast(`Discovered ${data.steps.length} wizard step(s) and ${data._columns_meta.available.length} columns!`, 'success');
      } else {
        showToast(`Discovered ${data.steps.length} wizard step(s)!`, 'success');
      }
    }

    if (!r.label && r.name) r.label = generateLabelFromName(r.name);
    renderCuicReports();
    markDirty();

  } catch(e) {
    showToast('Discovery failed: ' + e.message, 'error');
  } finally {
    btn.innerHTML = origHtml;
    btn.disabled  = false;
  }
}

// ══════════════════════════════════════════════════════════════════════════
//  COLUMNS PANEL
// ══════════════════════════════════════════════════════════════════════════

/**
 * Renders a collapsible panel for selecting which report columns to extract.
 * The first column (category/key) is always included and not shown.
 * report.columns = null  → all columns extracted
 * report.columns = []    → array of selected headerName strings
 */
function renderColumnsPanel(report, idx) {
  const meta = report._columns_meta;
  if (!meta || !meta.available || meta.available.length === 0) {
    // Only show the hint if wizard has already been discovered (so the user
    // knows what it's for), otherwise stay silent.
    if (report._wizard_meta || (report.filters && report.filters._meta)) {
      return `<details class="filter-panel-collapsible">
        <summary class="filter-panel-toggle">⚙ Column Selection
          <span style="font-size:11px;font-weight:normal;color:var(--muted);margin-left:8px">Re-run Validate Path to discover columns</span>
        </summary>
        <div class="filter-panel" style="padding:10px 14px;color:var(--muted);font-size:12px">
          No column data yet. Click <strong>Re-validate Path</strong> above to discover available columns.
        </div>
      </details>`;
    }
    return '';
  }

  // available[0] is the category column — skipped in the picker (always included)
  const pickable = meta.available.slice(1);
  const selCols  = report.columns;  // null = all, array = selected names
  const isAll    = selCols === null || selCols === undefined;
  const selSet   = isAll ? null : new Set(selCols);
  const selCount = isAll ? pickable.length : pickable.filter(c => selSet.has(c.headerName)).length;
  const cpId     = 'cp-' + idx;
  const discTs   = meta.discovered_at ? ` · discovered ${meta.discovered_at.replace('T', ' ').substring(0, 16)}` : '';

  let html = `<details class="filter-panel-collapsible">
    <summary class="filter-panel-toggle">⚙ Column Selection
      <span class="vl-badge">${selCount} / ${pickable.length} columns${discTs}</span>
      <span class="filter-clear" onclick="event.stopPropagation();columnsSelectAll(${idx},'${cpId}')">✔ All</span>
      <span class="filter-clear" style="margin-left:4px" onclick="event.stopPropagation();columnsSelectNone(${idx},'${cpId}')">✖ None</span>
    </summary>
    <div class="filter-panel">
      <div style="font-size:11px;color:var(--muted);margin-bottom:8px">
        The first column (${esc(meta.available[0].headerName || 'Category')}) is always included as the row identifier.
      </div>
      <div class="vl-toolbar" style="margin-bottom:6px">
        <input type="text" id="${cpId}-search" placeholder="🔍 Filter columns…" oninput="filterCpChecklist('${cpId}',this.value)" style="flex:1;min-width:120px">
        <button onclick="columnsSelectAll(${idx},'${cpId}')">✅ All</button>
        <button onclick="columnsSelectNone(${idx},'${cpId}')">☐ None</button>
        <span class="vl-count" id="${cpId}-count">${selCount} / ${pickable.length}</span>
      </div>
      <div class="vl-checklist" id="${cpId}-list">`;

  pickable.forEach(col => {
    const hn      = col.headerName || col.field || '';
    const checked = (isAll || selSet.has(hn)) ? 'checked' : '';
    html += `<label data-name="${attr(hn.toLowerCase())}">
      <input type="checkbox" value="${attr(hn)}" ${checked}
        onchange="columnsToggleItem(${idx},'${cpId}')">
      <span>${esc(hn)}</span></label>`;
  });

  html += `</div></div></details>`;
  return html;
}

function columnsToggleItem(reportIdx, cpId) {
  const r      = cuicReports[reportIdx];
  const listEl = document.getElementById(cpId + '-list');
  if (!listEl) return;
  const all   = listEl.querySelectorAll('input[type=checkbox]');
  const checked = Array.from(all).filter(cb => cb.checked).map(cb => cb.value);
  r.columns = checked.length === all.length ? null : checked;
  const ce = document.getElementById(cpId + '-count');
  if (ce) ce.textContent = checked.length + ' / ' + all.length;
  markDirty();
}

function columnsSelectAll(reportIdx, cpId) {
  const r      = cuicReports[reportIdx];
  const listEl = document.getElementById(cpId + '-list');
  if (listEl) {
    listEl.querySelectorAll('label').forEach(l => {
      if (l.style.display !== 'none') { const cb = l.querySelector('input'); if (cb) cb.checked = true; }
    });
  }
  r.columns = null;
  const all   = listEl ? listEl.querySelectorAll('input[type=checkbox]').length : 0;
  const ce    = document.getElementById(cpId + '-count');
  if (ce) ce.textContent = all + ' / ' + all;
  markDirty();
}

function columnsSelectNone(reportIdx, cpId) {
  const r      = cuicReports[reportIdx];
  const listEl = document.getElementById(cpId + '-list');
  if (listEl) {
    listEl.querySelectorAll('label').forEach(l => {
      if (l.style.display !== 'none') { const cb = l.querySelector('input'); if (cb) cb.checked = false; }
    });
  }
  r.columns = [];
  const all   = listEl ? listEl.querySelectorAll('input[type=checkbox]').length : 0;
  const ce    = document.getElementById(cpId + '-count');
  if (ce) ce.textContent = '0 / ' + all;
  markDirty();
}

function filterCpChecklist(cpId, query) {
  const listEl = document.getElementById(cpId + '-list');
  if (!listEl) return;
  const q = (query || '').toLowerCase();
  listEl.querySelectorAll('label').forEach(l => {
    l.style.display = (!q || (l.getAttribute('data-name') || '').includes(q)) ? '' : 'none';
  });
}
