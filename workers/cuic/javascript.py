"""
CUIC JavaScript Snippets
========================
JavaScript code injected into the browser for CUIC wizard reading and data scraping.
All snippets are AngularJS-aware and handle CUIC's custom UI components.
"""

# ── Multi-step wizard reader ─────────────────────────────────────────
# CUIC multi-step wizards use <filter-wizard> with wizardConfig.steps.
# Each step has its own Angular controller (HCFFilterCtrl for datetime,
# cuic-filter for valuelists, individual-filters for field filters).
# This JS reads the CURRENT visible step's data via Angular scopes.
CUIC_MULTISTEP_READ_JS = r'''() => {
    if (typeof angular === 'undefined') return {_debug: 'no_angular'};

    /* ── locate the filter-wizard element ── */
    const wizEl = document.querySelector('filter-wizard');
    if (!wizEl) return {_debug: 'no_filter_wizard_element',
        hasModal: !!document.querySelector('.modal-dialog'),
        hasRunReport: !!document.querySelector('run-report-filter'),
        bodyClasses: document.body.className.substring(0, 200)};
    let wizScope;
    try { wizScope = angular.element(wizEl).scope(); } catch(e) {
        return {_debug: 'scope_error', error: e.message};
    }
    if (!wizScope) return {_debug: 'no_scope_on_wizard'};

    /* Enhanced debug info collection */
    const debugInfo = {
        scopeKeys: Object.keys(wizScope).filter(k => !k.startsWith('$')).slice(0,30),
        allScopeKeys: Object.keys(wizScope).slice(0,30),
        parentKeys: wizScope.$parent ? Object.keys(wizScope.$parent).filter(k => !k.startsWith('$')).slice(0,30) : [],
        grandparentKeys: wizScope.$parent?.$parent ? Object.keys(wizScope.$parent.$parent).filter(k => !k.startsWith('$')).slice(0,30) : [],
    };
    
    /* Try isolateScope instead of regular scope */
    let isoScope = null;
    try {
        isoScope = angular.element(wizEl).isolateScope();
        if (isoScope) {
            debugInfo.hasIsolateScope = true;
            debugInfo.isoScopeKeys = Object.keys(isoScope).filter(k => !k.startsWith('$')).slice(0,30);
        }
    } catch(e) {}
    
    /* Walk up to find wizardConfig - check nested objects and parent chain */
    let wc = wizScope.wizardConfig 
          || isoScope?.wizardConfig
          || wizScope.runReportFilterForm?.wizardConfig
          || wizScope.ctrl?.wizardConfig
          || wizScope.vm?.wizardConfig
          || wizScope.$parent?.wizardConfig
          || wizScope.$parent?.$parent?.wizardConfig
          || wizScope.$parent?.$parent?.$parent?.wizardConfig;
    
    /* If still not found, try the controller directly with various names */
    if (!wc) {
        const ctrlNames = ['filterWizard', 'FilterWizardCtrl', 'wizardCtrl', 'runReportFilter'];
        for (const name of ctrlNames) {
            try {
                const ctrl = angular.element(wizEl).controller(name);
                if (ctrl) {
                    debugInfo.foundController = name;
                    debugInfo.ctrlKeys = Object.keys(ctrl).slice(0,30);
                    wc = ctrl.wizardConfig || ctrl.config || ctrl.steps;
                    if (wc) break;
                }
            } catch(e) {}
        }
    }
    
    /* Try to find steps directly on various scopes */
    if (!wc && !wc?.steps) {
        const stepsCheck = wizScope.steps || isoScope?.steps || wizScope.$parent?.steps;
        if (stepsCheck && Array.isArray(stepsCheck) && stepsCheck.length >= 2) {
            wc = {steps: stepsCheck};
            debugInfo.foundStepsDirectly = true;
        }
    }
    
    if (!wc) return {_debug: 'no_wizardConfig', ...debugInfo};
    if (!wc.steps || wc.steps.length < 2) return {_debug: 'not_multistep', stepsCount: wc.steps?.length || 0};

    /* Read step tabs (titles) */
    const stepTitles = wc.steps.map(s => s.title || s.wzTitle || '');

    /* Read the CURRENTLY VISIBLE step's filters */
    const sections = document.querySelectorAll('filter-wizard .steps > section');
    let currentIdx = -1;
    sections.forEach((sec, i) => {
        if (sec.style.display !== 'none') currentIdx = i;
    });
    if (currentIdx < 0) return null;

    const sec = sections[currentIdx];
    const stepTitle = stepTitles[currentIdx] || ('Step ' + (currentIdx+1));

    /* Detect what kind of filter is in this step */
    const result = {
        schemaVersion: 2,
        type: 'cuic_multistep',
        stepIndex: currentIdx,
        stepTitle: stepTitle,
        stepCount: wc.steps.length,
        stepTitles: stepTitles,
        params: []
    };

    /* ── DATETIME filter (HCFFilterCtrl / datetime-filter) ── */
    const dtFilter = sec.querySelector('datetime-filter');
    if (dtFilter) {
        /* The DateTimeFilterCtrl scope lives on an INNER element
           <div ng-controller="DateTimeFilterCtrl as sel">, NOT on the
           <datetime-filter> directive element itself. */
        const dtCtrlEl = dtFilter.querySelector('[ng-controller*="DateTimeFilter"]')
                      || dtFilter.querySelector('.dateTimeFilter');
        let dtScope;
        try {
            dtScope = dtCtrlEl ? angular.element(dtCtrlEl).scope()
                               : angular.element(dtFilter).scope();
        } catch(e) {}
        if (dtScope) {
            /* Read the heading text for label */
            const heading = sec.querySelector('.accordion--navigation a');
            const label = heading ? heading.textContent.replace(/[^a-zA-Z0-9_ ()]/g,'').trim() : 'DateTime';

            /* Date preset options */
            const datePresets = [];
            const selEl = dtFilter.querySelector('.csSelect-container');
            if (selEl) {
                try {
                    /* csSelect options live on isolateScope() */
                    const selIso = angular.element(selEl).isolateScope();
                    const selScope = angular.element(selEl).scope();
                    const opts = selIso?.csSelect?.options || selScope?.sel?.options || [];
                    opts.forEach(o => datePresets.push({
                        value: o.value || o.id || '',
                        label: o.label || o.name || o.value || ''
                    }));
                } catch(e) {}
            }
            /* If no options found from scope, try DOM */
            if (datePresets.length === 0) {
                dtFilter.querySelectorAll('.select-options li a').forEach(a => {
                    datePresets.push({value: a.title || a.textContent.trim(),
                                     label: a.textContent.trim()});
                });
            }

            /* ── Read ALL datetime state from Angular scope ── */
            /* dateTimeField + config live on the DateTimeFilterCtrl (as `sel`) child scope,
               which is accessible through angular.element(dtFilter).scope() after
               the controller initialises. */
            const dtField    = dtScope.dateTimeField   || dtScope.hcfCtrl?.historicalFilterField || {};
            const cfg        = dtScope.config          || {};
            const filterType = dtField.filterType      || 'DATETIME';

            /* relativeRange is the internal preset key (THISDAY, LASTDAY, CUSTOM, THISWEEK…) */
            const relativeRange  = dtField.relativeRange  || '';
            const isRelativeDate = dtField.isRelativeDate || 'yes'; /* 'yes'=date inputs disabled */
            const currentDate1   = dtField.startDate      || '';
            const currentDate2   = dtField.endDate        || '';

            /* Current preset: prefer relativeRange (definitive key), else fall back to toggle text */
            let currentPreset = relativeRange;
            if (!currentPreset) {
                const selText = dtFilter.querySelector('.select-toggle');
                currentPreset = selText ? selText.textContent.trim() : '';
                const matched = datePresets.find(p => p.label === currentPreset);
                if (matched) currentPreset = matched.value;
            }

            /* Time Range — only when filterType === 'DATETIME' */
            const hasTimeRange   = (filterType === 'DATETIME');
            const allTimeChecked = cfg.allTimeChecked || 'true';  /* 'true'=All Day, 'false'=Custom */
            const currentTime1   = cfg.startTime      || '';
            const currentTime2   = cfg.endTime        || '';

            /* Days section — visibility depends on TWO conditions:
               1. The datetime-filter must support days (template has the days section)
               2. The preset is NOT THISDAY or LASTDAY (toggled by ng-hide)
               We check daysKey existence AND template presence to confirm support. */
            const daysKey = dtScope.daysKey || ['mon','tue','wed','thu','fri','sat','sun'];
            const daysTemplateEl = dtFilter.querySelector('[ng-if="dateTimeField.showDays"], [ng-show*="showDays"], .days-filter, [ng-model*="allDay"]');
            const hasDaysData = daysKey.some(d => d in dtField);
            const hasDays = hasDaysData || !!daysTemplateEl;
            const allDayChecked = cfg.allDayChecked || 'true';   /* 'true'=All Day, 'false'=Custom */
            const days = {};
            daysKey.forEach(d => { days[d] = dtField[d] || ''; }); /* 'checked' or '' */

            /* Special report-linking modes */
            const isMatchField     = !!(dtScope.hcfCtrl?.isMatchField);
            const isMatchDateRange = !!(dtScope.hcfCtrl?.isMatchDateRange);
            const storageKey = dtField.parameterName || dtField.paramName || dtField.filterName || label;
            const aliases = Array.from(new Set([storageKey, label].filter(Boolean)));

            result.params.push({
                dataType:         filterType,
                type:             'cuic_datetime',
                label:            label,
                paramName:        storageKey,
                storageKey:       storageKey,
                aliases:          aliases,
                datePresets:      datePresets,
                currentPreset:    currentPreset,
                relativeRange:    relativeRange,
                isRelativeDate:   isRelativeDate,
                currentDate1:     currentDate1,
                currentDate2:     currentDate2,
                hasDateRange:     true,
                hasTimeRange:     hasTimeRange,
                allTimeChecked:   allTimeChecked,
                currentTime1:     currentTime1,
                currentTime2:     currentTime2,
                hasDays:          hasDays,
                allDayChecked:    allDayChecked,
                days:             days,
                isRequired:       true,
                isMatchField:     isMatchField,
                isMatchDateRange: isMatchDateRange
            });
        }
    }

    /* ── VALUELIST filter (cuic-filter / cuic-switcher) ── */
    const vlFilter = sec.querySelector('[ng-switch-when="VALUELIST"]');
    if (vlFilter) {
        const heading = sec.querySelector('.accordion--navigation a');
        const rawLabel = heading ? heading.textContent.trim() : 'Values';
        /* Extract label and paramName: "Call Types(CallTypeID)" → label="Call Types", paramName="CallTypeID" */
        const labelMatch = rawLabel.match(/^(.+?)\\s*\\(([^)]+)\\)\\s*$/);
        const label = labelMatch ? labelMatch[1].trim() : rawLabel;
        const paramName = labelMatch ? labelMatch[2].trim() : rawLabel;
        const storageKey = paramName || label || rawLabel;
        const aliases = Array.from(new Set([storageKey, paramName, label, rawLabel].filter(Boolean)));

        const leftPane = vlFilter.querySelector('[cuic-pane="left"]');
        const rightPane = vlFilter.querySelector('[cuic-pane="right"]');
        const switcherEl = vlFilter.querySelector('[cuic-switcher]');
        const allNames = [];
        const groups = [];
        const selectedNames = [];
        let _vlDebug = {};

        /* Helper: flatten a model array into allNames / groups */
        function collectFromModel(list, targetNames, targetGroups) {
            (list || []).forEach(v => {
                if (v.children && v.children.length > 0) {
                    const memberNames = [];
                    function flatMembers(items) {
                        (items || []).forEach(c => {
                            if (c.children && c.children.length > 0) flatMembers(c.children);
                            else memberNames.push(c.name || '');
                        });
                    }
                    flatMembers(v.children);
                    if (targetGroups) {
                        targetGroups.push({name: v.name || '',
                                         count: v.totalElements || v.children.length,
                                         members: memberNames});
                    }
                    memberNames.forEach(n => { if (!targetNames.includes(n)) targetNames.push(n); });
                } else {
                    const n = v.name || '';
                    if (n && !targetNames.includes(n)) targetNames.push(n);
                }
            });
        }

        /*
         * PRIMARY: Use isolateScope() on cuic-switcher or cuic-pane.
         * cuic-switcher directive binds: left-model → leftModel, right-model → rightModel
         * cuic-pane directive binds: model → model
         * isolateScope() returns the directive's OWN scope (not the vs-repeat child scope).
         * This bypasses virtual scrolling entirely.
         */

        /* Try cuic-switcher isolateScope first (has BOTH left and right models) */
        if (switcherEl) {
            try {
                const swIso = angular.element(switcherEl).isolateScope();
                if (swIso) {
                    _vlDebug.switcherIsoKeys = Object.keys(swIso).filter(k => !k.startsWith('$')).slice(0,30);
                    /* leftModel = full available list */
                    if (Array.isArray(swIso.leftModel) && swIso.leftModel.length > 0) {
                        collectFromModel(swIso.leftModel, allNames, groups);
                        _vlDebug.source = 'switcher.isolateScope.leftModel';
                        _vlDebug.rawCount = swIso.leftModel.length;
                    }
                    /* rightModel = full selected list */
                    if (Array.isArray(swIso.rightModel) && swIso.rightModel.length > 0) {
                        collectFromModel(swIso.rightModel, selectedNames, null);
                        _vlDebug.selectedSource = 'switcher.isolateScope.rightModel';
                    }
                }
            } catch(e) { _vlDebug.switcherIsoErr = e.message; }
        }

        /* Fallback: cuic-pane isolateScope for available values */
        if (leftPane && allNames.length === 0) {
            try {
                const lpIso = angular.element(leftPane).isolateScope();
                if (lpIso) {
                    _vlDebug.paneIsoKeys = Object.keys(lpIso).filter(k => !k.startsWith('$')).slice(0,30);
                    if (Array.isArray(lpIso.model) && lpIso.model.length > 0) {
                        collectFromModel(lpIso.model, allNames, groups);
                        _vlDebug.source = 'pane.isolateScope.model';
                        _vlDebug.rawCount = lpIso.model.length;
                    }
                }
            } catch(e) { _vlDebug.paneIsoErr = e.message; }
        }

        /* Fallback: walk scope chain to find item.lvaluelist */
        if (allNames.length === 0 && (switcherEl || leftPane)) {
            try {
                let s = angular.element(switcherEl || leftPane).scope();
                for (let depth = 0; s && depth < 10; depth++, s = s.$parent) {
                    if (s.item && Array.isArray(s.item.lvaluelist) && s.item.lvaluelist.length > 0) {
                        collectFromModel(s.item.lvaluelist, allNames, groups);
                        _vlDebug.source = 'scope.item.lvaluelist@depth' + depth;
                        _vlDebug.rawCount = s.item.lvaluelist.length;
                        break;
                    }
                }
            } catch(e) { _vlDebug.scopeWalkErr = e.message; }
        }

        /* Fallback: cuic-pane isolateScope for selected values */
        if (rightPane && selectedNames.length === 0) {
            try {
                const rpIso = angular.element(rightPane).isolateScope();
                if (rpIso && Array.isArray(rpIso.model) && rpIso.model.length > 0) {
                    collectFromModel(rpIso.model, selectedNames, null);
                    _vlDebug.selectedSource = 'pane.right.isolateScope.model';
                }
            } catch(e) {}
        }

        /* Fallback: scope chain for item.rvaluelist (selected values) */
        if (selectedNames.length === 0 && (switcherEl || rightPane)) {
            try {
                let s = angular.element(switcherEl || rightPane).scope();
                for (let depth = 0; s && depth < 10; depth++, s = s.$parent) {
                    if (s.item && Array.isArray(s.item.rvaluelist) && s.item.rvaluelist.length > 0) {
                        collectFromModel(s.item.rvaluelist, selectedNames, null);
                        _vlDebug.selectedSource = 'scope.item.rvaluelist@depth' + depth;
                        break;
                    }
                }
            } catch(e) {}
        }

        /* Last resort: read what's visible in DOM (partial, only rendered items) */
        if (leftPane && allNames.length === 0) {
            leftPane.querySelectorAll('.cuic-switcher-name').forEach(el => {
                const name = (el.title || el.textContent || '').trim();
                if (name && !allNames.includes(name)) allNames.push(name);
            });
            _vlDebug.source = 'dom_fallback';
            _vlDebug.partial = true;
        }
        if (rightPane && selectedNames.length === 0) {
            rightPane.querySelectorAll('.cuic-switcher-name').forEach(el => {
                const name = (el.title || el.textContent || '').trim();
                if (name && !selectedNames.includes(name)) selectedNames.push(name);
            });
        }

        /* Read the "Available: N Values" text to get total expected count */
        let totalAvailable = allNames.length;
        const totalLabel = (leftPane || vlFilter).querySelector('.cuic-switcher-total-label .ng-binding');
        if (totalLabel) {
            const m = totalLabel.textContent.match(/(\\d+)\\s*Values?/i);
            if (m) totalAvailable = parseInt(m[1], 10);
        }

        result.params.push({
            dataType: 'VALUELIST',
            type: 'cuic_valuelist',
            label: label,
            paramName: paramName,
            storageKey: storageKey,
            aliases: aliases,
            isRequired: true,
            totalAvailable: totalAvailable,
            availableCount: allNames.length,
            availableNames: allNames,
            availableGroups: groups,
            selectedCount: selectedNames.length,
            selectedValues: selectedNames,
            _vlDebug: _vlDebug,
            _needsScroll: allNames.length < totalAvailable
        });
    }

    /* ── Individual Field Filters (step 3 type) ── */
    const iffFields = sec.querySelector('#cuic-iff-fields');
    if (iffFields) {
        const availableFields = [];
        iffFields.querySelectorAll('.select-options li a').forEach(a => {
            const txt = (a.title || a.textContent || '').trim();
            const m = txt.match(/^(.+?)\\s*\\(([^)]+)\\)\\s*$/);
            availableFields.push({
                label: m ? m[1].trim() : txt,
                fieldId: m ? m[2].trim() : txt,
                combined: txt
            });
        });

        /* Capture already-selected fields from the Angular vm.selectedList.
           Also read per-field operator and filter value(s) for a full clone
           of the field-filter configuration that can be saved and replayed. */
        let selectedFieldIds   = [];
        let selectedFields     = []; /* full detail: {fieldId, label, operator, value1, value2} */
        let availableOperators = []; /* operator options read from the first operator csSelect */
        try {
            const selectedFieldMap = new Map();

            function pushOperatorOptions(opts) {
                (opts || []).forEach(o => {
                    const value = o.operator || o.value || o.id || '';
                    const label = o.label || o.name || '';
                    if (!value && !label) return;
                    if (!availableOperators.some(op => op.value === value && op.label === label)) {
                        availableOperators.push({value, label});
                    }
                });
            }

            function mergeSelectedField(f) {
                if (!f) return;
                const cn  = (f.combinedName || '').trim();
                const pm  = cn.match(/^(.+?)\\s*\\(([^)]+)\\)\\s*$/);
                const fid = String(pm ? pm[2].trim() : (f.fieldId || f.id || f.name || f.fieldName || cn || '')).trim();
                if (!fid) return;
                const lbl = String(pm ? pm[1].trim() : (f.label || f.name || cn || fid)).trim();
                let op = f.operator;
                if (!op && f.selected) op = f.selected;
                if (op && typeof op === 'object') op = op.operator || op.value || op.id || op.label || String(op);

                if (!selectedFieldIds.includes(fid)) selectedFieldIds.push(fid);

                const existing = selectedFieldMap.get(fid) || {
                    fieldId: fid,
                    label: lbl,
                    operator: '',
                    value1: '',
                    value2: '',
                    showInput2: false
                };

                if (lbl) existing.label = lbl;
                if (op) existing.operator = String(op);
                if (f.value1 !== undefined && String(f.value1) !== '') existing.value1 = String(f.value1);
                if (f.value2 !== undefined && String(f.value2) !== '') existing.value2 = String(f.value2);
                if (f.showInput2 !== undefined) existing.showInput2 = !!f.showInput2;

                selectedFieldMap.set(fid, existing);
            }

            function findVmScope(rootEl) {
                const scopes = [];
                try { scopes.push(angular.element(rootEl).scope()); } catch(e) {}
                try { scopes.push(angular.element(rootEl).isolateScope()); } catch(e) {}
                for (let i = 0; i < scopes.length; i++) {
                    let s = scopes[i];
                    for (let d = 0; s && d < 8; d++, s = s.$parent) {
                        if (s.vm && Array.isArray(s.vm.selectedList)) return s;
                    }
                }
                return null;
            }

            const iffScope = findVmScope(iffFields);
            if (iffScope && iffScope.vm && Array.isArray(iffScope.vm.selectedList)) {
                /* Try to collect operator options from operator csSelect (isolateScope) */
                const opSelEls = iffFields.querySelectorAll('.csSelect-container');
                const opSelEl = opSelEls.length > 1 ? opSelEls[1] : opSelEls[0];
                if (opSelEl) {
                    try {
                        const opSelIso = angular.element(opSelEl).isolateScope();
                        const opSelScope = angular.element(opSelEl).scope();
                        pushOperatorOptions(opSelIso?.csSelect?.options || opSelScope?.sel?.options || []);
                    } catch(e) {}
                }
                iffScope.vm.selectedList.forEach(mergeSelectedField);
            }

            const cfEls = iffFields.querySelectorAll('cuic-filter');
            cfEls.forEach(cfEl => {
                try {
                    let cfScope = angular.element(cfEl).scope();
                    let fc = cfScope && cfScope.filterCtrl;
                    if (!fc) {
                        const iso = angular.element(cfEl).isolateScope();
                        fc = iso && iso.filterCtrl;
                    }
                    if (!fc) {
                        let cs = cfScope && cfScope.$$childHead;
                        for (let d = 0; !fc && cs && d < 8; d++, cs = cs.$$nextSibling) {
                            fc = cs.filterCtrl;
                            if (!fc && cs.$$childHead) {
                                let cs2 = cs.$$childHead;
                                for (let d2 = 0; !fc && cs2 && d2 < 5; d2++, cs2 = cs2.$$nextSibling) {
                                    fc = cs2.filterCtrl;
                                }
                            }
                        }
                    }
                    if (!fc || !fc.filterField) return;
                    const ft = fc.filterField.filterType;
                    if (fc.options && ft) pushOperatorOptions(fc.options[ft] || []);
                    mergeSelectedField(fc.filterField);
                } catch(e) {}
            });

            const rowEls = iffFields.querySelectorAll('.accordion--cuic-accordion');
            rowEls.forEach(rowEl => {
                try {
                    const headingEl = rowEl.querySelector('a[cs-accordion-transclude="heading"]');
                    const headingText = headingEl
                        ? String(headingEl.title || headingEl.textContent || '').replace(/\s+/g, ' ').trim()
                        : '';
                    const headingMatch = headingText.match(/^(.+?)\s*\(([^)]+)\)\s*$/);
                    const rowFieldId = headingMatch ? headingMatch[2].trim() : headingText;
                    const rowLabel = headingMatch ? headingMatch[1].trim() : headingText;
                    if (!rowFieldId) return;

                    const operatorSelect = rowEl.querySelector('.indFilter_select select.hidden-select, .indFilter_select select');
                    if (operatorSelect) {
                        pushOperatorOptions(Array.from(operatorSelect.options || []).map(o => ({
                            value: o.value || '',
                            label: (o.textContent || '').trim()
                        })));
                    }

                    const value1Input = rowEl.querySelector('input[ng-model="filterCtrl.filterField.value1"], input[ng-model*="value1"]');
                    const value2Input = rowEl.querySelector('input[ng-model="filterCtrl.filterField.value2"], input[ng-model*="value2"]');

                    mergeSelectedField({
                        fieldId: rowFieldId,
                        label: rowLabel,
                        combinedName: headingText,
                        operator: operatorSelect ? String(operatorSelect.value || '').trim() : '',
                        value1: value1Input ? String(value1Input.value || '').trim() : '',
                        value2: value2Input ? String(value2Input.value || '').trim() : '',
                        showInput2: !!value2Input
                    });
                } catch(e) {}
            });

            selectedFields = Array.from(selectedFieldMap.values());
        } catch(e) {}

        result.params.push({
            dataType:           'FIELD_FILTER',
            type:               'cuic_field_filter',
            label:              'Field Filters',
            paramName:          '_field_filters',
            storageKey:         '_field_filters',
            aliases:            ['_field_filters', 'Field Filters'],
            availableFields:    availableFields,
            availableOperators: availableOperators,
            selectedFieldIds:   selectedFieldIds,
            selectedFields:     selectedFields
        });
    }

    return result.params.length > 0 ? result : null;
}'''  # noqa: E501

# ── SPAB (single-step) wizard reader ─────────────────────────────────
# CUIC uses custom AngularJS widgets (csSelect, cuic-datetime,
# cuic-switcher) – standard HTML form scraping won't work.
# This JS reads filter params via Angular's scope API.
CUIC_WIZARD_READ_JS = r'''() => {
    if (typeof angular === 'undefined') return null;
    const el = document.querySelector('[ng-controller="spabCtrl as spab"]');
    if (!el) return null;
    let scope;
    try { scope = angular.element(el).scope(); } catch(e) { return null; }
    if (!scope || !scope.spab || !scope.spab.data) return null;

    const datePresets = (scope.spab.dateDropdownOptions || []).map(o => ({
        value: o.value, label: o.label
    }));

    /* DOM containers: the ng-repeat divs for non-hardcoded items */
    const containers = document.querySelectorAll(
        'spab-filters > div[ng-repeat="item in spab.data"]'
    );

    const params = [];
    let vi = 0;
    scope.spab.data.forEach(item => {
        if (item.hardCodedValue) return;

        /* label & param name from DOM */
        let label = '', paramName = '', paramName2 = '';
        const c = containers[vi];
        if (c) {
            const spans = c.querySelectorAll('.spab_name .ellipses, .spab_name .ellipsis');
            if (spans.length >= 2) {
                label     = (spans[0].title || spans[0].textContent || '').trim();
                paramName = (spans[1].title || spans[1].textContent || '').trim();
            }
            if (spans.length >= 3) {
                paramName2 = (spans[2].title || spans[2].textContent || '').trim();
            }
            if (spans.length === 1) {
                label = (spans[0].title || spans[0].textContent || '').trim();
            }
        }
        /* fallback: try scope item properties */
        if (!label)     label     = item.displayName || item.filterName || item.name || '';
        if (!paramName) paramName = item.parameterName || item.paramName || '';

        const storageKey = paramName || paramName2 || label;
        const aliases = Array.from(new Set([storageKey, paramName, paramName2, label].filter(Boolean)));
        const p = {dataType: item.dataType, label, paramName, paramName2,
               storageKey, aliases, isRequired: !!item.isRequired};

        switch (item.dataType) {
            case 'DATETIME':
            case 'DATE':
                p.type = 'cuic_datetime';
                p.datePresets = datePresets;
                p.currentPreset = (item.date1 && item.date1.dropDownSelected)
                    ? item.date1.dropDownSelected.value : '';
                p.relativeRange = p.currentPreset; /* alias for multistep compat */
                p.hasDateRange = !!item.date2;
                /* enablePicker: true when preset is CUSTOM, false otherwise */
                p.enablePicker = !!item.enablePicker;
                p.isRelativeDate = item.enablePicker ? 'no' : 'yes';
                p.displayFormat = item.displayFormat || '';
                /* current date values: prefer .date (formatted string), fallback .dateValue */
                if (item.date1)
                    p.currentDate1 = item.date1.date || item.date1.dateValue || '';
                if (item.date2)
                    p.currentDate2 = item.date2.date || item.date2.dateValue || '';
                /* time range */
                p.allTime = item.allTime || 1;
                p.hasTimeRange = (item.dataType !== 'DATE' && !!item.date2);
                p.allTimeChecked = (item.allTime === 1) ? 'true' : 'false';
                if (item.time1)
                    p.currentTime1 = item.time1.date || item.time1.dateValue || '';
                if (item.time2)
                    p.currentTime2 = item.time2.date || item.time2.dateValue || '';
                /* Days of week: only present on some report definitions.
                   item.days is a map {mon:'checked',tue:'',...} when supported.
                   showDays is toggled by handleRelativeDateChange when
                   preset !== THISDAY and preset !== LASTDAY. */
                p.hasDays = ('days' in item) && !!item.days;
                if (p.hasDays) {
                    const preset = p.currentPreset;
                    p.showDays = (preset !== 'THISDAY' && preset !== 'LASTDAY');
                    p.allDay = item.allDay;
                    p.allDayChecked = item.allDay ? 'true' : 'false';
                    const dayKeys = ['mon','tue','wed','thu','fri','sat','sun'];
                    p.days = {};
                    dayKeys.forEach(d => { p.days[d] = item.days[d] || item[d] || ''; });
                } else {
                    p.showDays = false;
                    p.allDayChecked = 'true';
                    p.days = {mon:'checked',tue:'checked',wed:'checked',thu:'checked',
                              fri:'checked',sat:'checked',sun:'checked'};
                }
                break;
            case 'VALUELIST': {
                p.type = 'cuic_valuelist';
                const left  = item.lvaluelist || [];
                const right = item.rvaluelist || [];
                p.selectedCount   = right.length;
                p.selectedValues  = right.map(v => v.name || '');
                /* collect ALL available names (flatten groups) */
                const allNames = [];
                const groups = [];
                function collectNames(list) {
                    (list || []).forEach(v => {
                        if (v.children && v.children.length > 0) {
                            const memberNames = [];
                            function flatMembers(items) {
                                (items || []).forEach(c => {
                                    if (c.children && c.children.length > 0) flatMembers(c.children);
                                    else memberNames.push(c.name || '');
                                });
                            }
                            flatMembers(v.children);
                            groups.push({name: v.name || '',
                                         count: v.totalElements || v.children.length,
                                         members: memberNames});
                            memberNames.forEach(n => allNames.push(n));
                        } else {
                            allNames.push(v.name || '');
                        }
                    });
                }
                collectNames(left);
                p.availableCount  = allNames.length;
                p.availableNames  = allNames;
                p.availableGroups = groups;
                break;
            }
            case 'STRING':
                p.type = 'text';
                p.currentValue = item.value || '';
                break;
            case 'DECIMAL':
                p.type = 'number';
                p.currentValue = item.value !== undefined ? String(item.value) : '';
                break;
            case 'BOOLEAN':
                p.type = 'checkbox';
                p.currentValue = !!item.value;
                break;
            default:
                p.type = 'text';
                p.currentValue = '';
        }
        params.push(p);
        vi++;
    });

    return {schemaVersion: 2, type: 'cuic_spab', params, datePresets};
}'''  # noqa: E501

# Apply saved filter values via Angular scope manipulation.
CUIC_WIZARD_APPLY_JS = r'''(config) => {
    if (typeof angular === 'undefined') return {error: 'angular not loaded'};
    const el = document.querySelector('[ng-controller="spabCtrl as spab"]');
    if (!el) return {error: 'spab controller not found'};
    const scope = angular.element(el).scope();
    if (!scope || !scope.spab || !scope.spab.data) return {error: 'spab data missing'};

    const containers = document.querySelectorAll(
        'spab-filters > div[ng-repeat="item in spab.data"]'
    );
    const results = [];
    let vi = 0;

    function pad2(value) {
        return String(value).padStart(2, '0');
    }
    function parseCuicTimeValue(value) {
        if (value instanceof Date)
            return isNaN(value.getTime()) ? null : new Date(value.getTime());
        const text = String(value || '').trim();
        if (!text) return null;

        const direct = new Date(text);
        if (!isNaN(direct.getTime())) return direct;

        const match = text.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?$/i);
        if (!match) return null;

        let hours = parseInt(match[1], 10);
        const minutes = parseInt(match[2], 10);
        const seconds = parseInt(match[3] || '0', 10);
        const meridiem = (match[4] || '').toUpperCase();

        if (meridiem) {
            if (hours === 12) hours = 0;
            if (meridiem === 'PM') hours += 12;
        }
        if (hours > 23 || minutes > 59 || seconds > 59) return null;

        const parsed = new Date();
        parsed.setHours(hours, minutes, seconds, 0);
        return parsed;
    }
    function applyCuicTimeValue(target, value) {
        if (!target) return false;
        const parsed = parseCuicTimeValue(value);
        if (!parsed) return false;
        target.dateValue = parsed;
        target.date = pad2(parsed.getHours()) + ':' + pad2(parsed.getMinutes()) + ':' + pad2(parsed.getSeconds());
        return true;
    }
    function flattenCuicList(list) {
        const out = [];
        (list || []).forEach(v => {
            if (v.children && v.children.length)
                out.push(...flattenCuicList(v.children));
            else
                out.push(v);
        });
        return out;
    }
    function uniqueCuicNames(values) {
        const seen = new Set();
        const out = [];
        (values || []).forEach(value => {
            const name = String(value || '').trim();
            if (!name || seen.has(name)) return;
            seen.add(name);
            out.push(name);
        });
        return out;
    }
    function replaceCuicValueListSelection(item, requestedNames) {
        const targetNames = uniqueCuicNames(requestedNames);
        const pool = flattenCuicList(item.lvaluelist).concat(flattenCuicList(item.rvaluelist));
        const itemByName = new Map();
        pool.forEach(entry => {
            const name = entry && entry.name ? String(entry.name).trim() : '';
            if (!name || itemByName.has(name)) return;
            itemByName.set(name, entry);
        });

        const selected = [];
        targetNames.forEach(name => {
            const entry = itemByName.get(name);
            if (entry) selected.push(entry);
        });

        const selectedSet = new Set(targetNames);
        const available = [];
        itemByName.forEach((entry, name) => {
            if (!selectedSet.has(name)) available.push(entry);
        });

        item.rvaluelist = selected;
        item.lvaluelist = available;
        if (item.filterField)
            item.filterField.value = selected;
        return selected;
    }

    scope.spab.data.forEach(item => {
        if (item.hardCodedValue) return;
        const c = containers[vi];

        /* resolve param name from DOM */
        let paramName = '';
        if (c) {
            const spans = c.querySelectorAll('.spab_name .ellipses, .spab_name .ellipsis');
            if (spans.length >= 2)
                paramName = (spans[1].title || spans[1].textContent || '').trim();
        }
        if (!paramName) paramName = item.parameterName || item.paramName || '';

        const val = config[paramName];
        if (val === undefined || val === null) { vi++; return; }

        try {
            switch (item.dataType) {
                case 'DATETIME':
                case 'DATE': {
                    /* val can be a string preset like "THISDAY"
                       or an object: {preset, date1, date2, allTime, time1, time2,
                                      allTimeChecked, allDayChecked, days, showDays} */
                    const cfg = typeof val === 'string' ? {preset: val} : (val || {});
                    const preset = cfg.preset || null;

                    if (preset && item.date1) {
                        const opt = (scope.spab.dateDropdownOptions || [])
                            .find(o => o.value === preset);
                        if (opt) {
                            item.date1.dropDownSelected = opt;
                            if (scope.spab.handleRelativeDateChange)
                                scope.spab.handleRelativeDateChange(item);
                        }
                    }
                    /* custom date values */
                    if (preset === 'CUSTOM') {
                        if (cfg.date1 && item.date1) {
                            const d = new Date(cfg.date1);
                            if (!isNaN(d)) item.date1.dateValue = d;
                        }
                        if (cfg.date2 && item.date2) {
                            const d = new Date(cfg.date2);
                            if (!isNaN(d)) item.date2.dateValue = d;
                        }
                    }
                    /* time range: 1=All Day, 2=Custom */
                    /* Accept both allTime (1/2) and allTimeChecked ('true'/'false') */
                    let resolvedAllTime = cfg.allTime;
                    if (resolvedAllTime === undefined && cfg.allTimeChecked !== undefined)
                        resolvedAllTime = cfg.allTimeChecked === 'false' ? 2 : 1;
                    if (resolvedAllTime !== undefined)
                        item.allTime = Number(resolvedAllTime);
                    if (item.allTime === 2) {
                        applyCuicTimeValue(item.time1, cfg.time1);
                        applyCuicTimeValue(item.time2, cfg.time2);
                    }
                    /* Days of week — only when item.days exists on the model */
                    if (item.days || 'days' in item) {
                        if (cfg.allDayChecked !== undefined) {
                            item.allDay = (cfg.allDayChecked === 'true' || cfg.allDayChecked === true);
                        }
                        if (cfg.days) {
                            const dayKeys = ['mon','tue','wed','thu','fri','sat','sun'];
                            dayKeys.forEach(d => {
                                if (cfg.days[d] !== undefined) {
                                    if (item.days) item.days[d] = cfg.days[d];
                                    item[d] = cfg.days[d]; /* 'checked' or '' */
                                }
                            });
                        }
                    }
                    results.push({param: paramName, ok: true, value: cfg});
                    break;
                }
                case 'VALUELIST': {
                    if (val === 'all') {
                        /* click "Move all items right" */
                        const btn = c ? c.querySelector('.icon-right-all') : null;
                        if (btn) { btn.click(); }
                        else {
                            replaceCuicValueListSelection(
                                item,
                                flattenCuicList(item.lvaluelist)
                                    .concat(flattenCuicList(item.rvaluelist))
                                    .map(entry => entry && entry.name)
                            );
                        }
                        results.push({param: paramName, ok: true, value: 'all'});
                    } else if (Array.isArray(val) && val.length) {
                        const toMove = replaceCuicValueListSelection(item, val);
                        results.push({param: paramName, ok: true,
                                      value: toMove.map(v=>v.name)});
                    }
                    break;
                }
                case 'STRING':
                case 'DECIMAL':
                    item.value = val;
                    results.push({param: paramName, ok: true, value: val});
                    break;
                case 'BOOLEAN':
                    item.value = !!val;
                    results.push({param: paramName, ok: true, value: val});
                    break;
            }
        } catch(e) {
            results.push({param: paramName, ok: false, error: e.message});
        }
        vi++;
    });

    try { scope.$apply(); } catch(e) { /* digest may already be running */ }
    return {applied: results};
}'''  # noqa: E501

# Apply saved filter values to the CURRENTLY VISIBLE multi-step wizard step.
# cfg = {stepType: 'datetime' | 'valuelist' | 'field_filter', values: {...}}
# Returns {ok: bool, actions: [...], error: ''}
CUIC_MULTISTEP_APPLY_JS = r'''(cfg) => {
    if (typeof angular === 'undefined') return {ok: false, error: 'no_angular'};

    /* Find the currently visible step section */
    const sections = document.querySelectorAll('filter-wizard .steps > section');
    let sec = null;
    sections.forEach(s => { if (s.style.display !== 'none') sec = s; });
    if (!sec) return {ok: false, error: 'no_visible_section'};

    const vals    = cfg.values || {};
    const actions = [];

    /* ─────────────────────────────────────────────────────────── DATETIME */
    if (cfg.stepType === 'datetime') {
        const dtFilter = sec.querySelector('datetime-filter');
        if (!dtFilter) return {ok: false, error: 'no_datetime_filter'};

        /* The datetime-filter directive creates an OUTER scope on the
           <datetime-filter> tag itself, but the DateTimeFilterCtrl with
           relativeRangeSelected, updateRDChange, dateTimeField, config,
           daysKey etc. lives on an INNER element:
             <div ng-controller="DateTimeFilterCtrl as sel">
           We must get scope() from THAT inner element. */
        const dtCtrlEl = dtFilter.querySelector('[ng-controller*="DateTimeFilter"]')
                      || dtFilter.querySelector('.dateTimeFilter');
        let scope;
        try {
            scope = dtCtrlEl ? angular.element(dtCtrlEl).scope()
                             : angular.element(dtFilter).scope();
        } catch(e) { return {ok: false, error: e.message}; }
        if (!scope) return {ok: false, error: 'no_scope'};

        try {
            /* ── Preset / date range dropdown ── */
            if (vals.preset !== undefined) {
                const selEl = dtFilter.querySelector('.csSelect-container');
                if (selEl) {
                    /* csSelect options live on isolateScope(), sel.options on regular scope */
                    const selIso = angular.element(selEl).isolateScope();
                    const selScope = angular.element(selEl).scope();
                    const opts = selIso?.csSelect?.options || selScope?.sel?.options || [];
                    const opt  = opts.find(o =>
                        (o.value || o.id || '') === vals.preset ||
                        (o.label || o.name  || '') === vals.preset);
                    if (opt) {
                        scope.relativeRangeSelected = opt;
                        if (selIso && selIso.csSelect) selIso.csSelect.selected = opt;
                        if (typeof scope.updateRDChange === 'function') scope.updateRDChange(0);
                        actions.push({field: 'preset', value: vals.preset, ok: true});
                    } else {
                        actions.push({field: 'preset', value: vals.preset, ok: false,
                                      error: 'option_not_found'});
                    }
                }
            }
            /* ── Custom date values ── */
            if (vals.date1 !== undefined && scope.dateTimeField) {
                scope.dateTimeField.startDate = vals.date1;
                actions.push({field: 'date1', value: vals.date1, ok: true});
            }
            if (vals.date2 !== undefined && scope.dateTimeField) {
                scope.dateTimeField.endDate = vals.date2;
                actions.push({field: 'date2', value: vals.date2, ok: true});
            }
            /* ── Time Range ── */
            /* Accept both allTimeChecked ("true"/"false") and legacy allTime (1=All Day, 2=Custom) */
            let resolvedAllTime = vals.allTimeChecked;
            if (resolvedAllTime === undefined && vals.allTime !== undefined)
                resolvedAllTime = (vals.allTime === 2) ? 'false' : 'true';
            if (resolvedAllTime !== undefined && scope.config) {
                scope.config.allTimeChecked = String(resolvedAllTime);
                if (typeof scope.updateAllTime === 'function') scope.updateAllTime();
                actions.push({field: 'allTimeChecked', value: resolvedAllTime, ok: true});
            }
            if (vals.time1 !== undefined && scope.config) {
                scope.config.startTime = vals.time1;
                actions.push({field: 'time1', value: vals.time1, ok: true});
            }
            if (vals.time2 !== undefined && scope.config) {
                scope.config.endTime = vals.time2;
                actions.push({field: 'time2', value: vals.time2, ok: true});
            }
            /* ── Days of week ── */
            if (vals.allDayChecked !== undefined && scope.config) {
                scope.config.allDayChecked = String(vals.allDayChecked);
                if (typeof scope.updateAllDays === 'function') scope.updateAllDays();
                actions.push({field: 'allDayChecked', value: vals.allDayChecked, ok: true});
            }
            if (vals.days && scope.dateTimeField) {
                const daysKey = scope.daysKey || ['mon','tue','wed','thu','fri','sat','sun'];
                daysKey.forEach(d => {
                    if (vals.days[d] !== undefined) {
                        scope.dateTimeField[d] = vals.days[d]; /* 'checked' or '' */
                        actions.push({field: 'day_' + d, value: vals.days[d], ok: true});
                    }
                });
            }
            try { scope.$apply(); } catch(e) {}
        } catch(e) {
            return {ok: false, error: e.message, actions};
        }
    }

    /* ────────────────────────────────────────────────────────── VALUELIST */
    else if (cfg.stepType === 'valuelist') {
        const vlFilter = sec.querySelector('[ng-switch-when="VALUELIST"]');
        if (!vlFilter) return {ok: false, error: 'no_valuelist_filter'};
        const switcherEl = vlFilter.querySelector('[cuic-switcher]');

        function flattenModel(list) {
            const out = [];
            (list||[]).forEach(v => {
                if (v.children && v.children.length) out.push(...flattenModel(v.children));
                else out.push(v);
            });
            return out;
        }
        function extractByName(list, names) {
            const matched = [], rest = [];
            (list||[]).forEach(v => {
                if (v.children && v.children.length) {
                    const m = [], r = [];
                    v.children.forEach(ch => {
                        if (names.includes(ch.name)) m.push(ch); else r.push(ch);
                    });
                    matched.push(...m);
                    if (r.length) rest.push(Object.assign({}, v, {children: r}));
                } else {
                    if (names.includes(v.name)) matched.push(v); else rest.push(v);
                }
            });
            return [matched, rest];
        }
        function findFilterCtrl() {
            const cuicFilter = sec.querySelector('cuic-filter');
            if (!cuicFilter) return null;
            try {
                let s = angular.element(cuicFilter).scope();
                for (let d = 0; s && d < 6; d++, s = s.$parent) {
                    if (s.filterCtrl) return s.filterCtrl;
                    if (s.ctrl && s.ctrl.filterField) return s.ctrl;
                }
            } catch(e) {}
            return null;
        }

        try {
            let swIso = null;
            if (switcherEl) {
                try { swIso = angular.element(switcherEl).isolateScope(); } catch(e) {}
            }

            if (vals.selectedValues === 'all') {
                const btn = vlFilter.querySelector('.icon-right-all');
                if (btn) {
                    btn.click();
                    actions.push({field: 'all', method: 'button', ok: true});
                } else if (swIso && Array.isArray(swIso.leftModel)) {
                    swIso.rightModel = (swIso.rightModel||[]).concat(flattenModel(swIso.leftModel));
                    swIso.leftModel  = [];
                    try { swIso.$apply(); } catch(e) {}
                    actions.push({field: 'all', method: 'switcher_iso', ok: true});
                } else {
                    const fc = findFilterCtrl();
                    if (fc && fc.filterField) {
                        fc.filterField.value = flattenModel(fc.leftAttributes || []);
                        fc.leftAttributes    = [];
                        const cf2 = sec.querySelector('cuic-filter');
                        try { if(cf2) angular.element(cf2).scope().$apply(); } catch(e) {}
                        actions.push({field: 'all', method: 'filterCtrl', ok: true});
                    } else {
                        actions.push({field: 'all', ok: false, error: 'no_apply_method'});
                    }
                }
            } else if (Array.isArray(vals.selectedValues) && vals.selectedValues.length) {
                /* Replace selection atomically: merge left+right, then split by saved names in one pass */
                if (swIso && Array.isArray(swIso.leftModel)) {
                    const allRight = flattenModel(swIso.rightModel || []);
                    /* Deduplicate combined list by name before re-splitting */
                    const rawCombined = (swIso.leftModel || []).concat(allRight);
                    const seenNames = new Set();
                    const combined = [];
                    rawCombined.forEach(v => {
                        const n = v.name || '';
                        if (!seenNames.has(n)) { seenNames.add(n); combined.push(v); }
                    });
                    const leftCount = swIso.leftModel.length;
                    const rightCount = allRight.length;
                    const [toMove, remaining] = extractByName(combined, vals.selectedValues);
                    swIso.leftModel  = remaining;
                    swIso.rightModel = toMove;
                    try { swIso.$apply(); } catch(e) {}
                    actions.push({field: 'selectedValues', count: toMove.length,
                                  requested: vals.selectedValues.length,
                                  matchedNames: toMove.map(v => v.name || '?'),
                                  leftBefore: leftCount, rightBefore: rightCount,
                                  combined: combined.length,
                                  method: 'switcher_iso', ok: true});
                } else {
                    const fc = findFilterCtrl();
                    if (fc && fc.filterField) {
                        const leftAttrs = fc.leftAttributes || [];
                        const rightAttrs = flattenModel(fc.filterField.value || []);
                        const combined = leftAttrs.concat(rightAttrs);
                        const leftCount = leftAttrs.length;
                        const rightCount = rightAttrs.length;
                        const [toMove, remaining] = extractByName(combined, vals.selectedValues);
                        fc.leftAttributes    = remaining;
                        fc.filterField.value = toMove;
                        const cf2 = sec.querySelector('cuic-filter');
                        try { if(cf2) angular.element(cf2).scope().$apply(); } catch(e) {}
                        actions.push({field: 'selectedValues', count: toMove.length,
                                      requested: vals.selectedValues.length,
                                      matchedNames: toMove.map(v => v.name || '?'),
                                      leftBefore: leftCount, rightBefore: rightCount,
                                      combined: combined.length,
                                      method: 'filterCtrl', ok: true});
                    } else {
                        actions.push({field: 'selectedValues', ok: false, error: 'no_apply_method'});
                    }
                }
            }
        } catch(e) {
            return {ok: false, error: e.message, actions};
        }
    }

    /* ──────────────────────────────────────────────────────── FIELD FILTER */
    /* Pass 1: add fields to vm.selectedList, trigger $apply() so Angular
       renders cuic-filter directive rows.  Operator/value are set in a
       separate Pass 2 call after the DOM elements have compiled.  */
    else if (cfg.stepType === 'field_filter') {
        const iffFields = sec.querySelector('#cuic-iff-fields');
        if (!iffFields) return {ok: false, error: 'no_iff_fields'};

        try {
            const iffScope = angular.element(iffFields).scope();
            let vm = iffScope && iffScope.vm;
            let s = iffScope;
            for (let d = 0; !vm && s && d < 5; d++, s = s.$parent) {
                vm = s.vm;
            }
            if (!vm || !vm.selectedList) return {ok: false, error: 'no_vm_selectedList'};

            const fieldsToApply = vals.fields || [];
            if (fieldsToApply.length === 0) {
                try { iffScope.$apply(); } catch(e) {}
                return {ok: true, actions: []};
            }

            /* Clear existing selection so we replace with saved fields */
            vm.selectedList.length = 0;
            const availableOpts = vm.fields || [];
            if (!availableOpts.length) {
                try { iffScope.$apply(); } catch(e) {}
                return {ok: false, error: 'no_vm_fields', actions: []};
            }

            /* Add each saved field to selectedList.
               value1/value2/selected are pre-set on the entry for completeness,
               but Angular's cuic-filter directive may overwrite them during
               its init phase.  The reliable set happens in Pass 2. */
            fieldsToApply.forEach(fv => {
                const fvId = (fv.fieldId || fv.id || '').trim();
                const opt = availableOpts.find(o => {
                    const oid = (o.fieldId || o.id || o.name || '').trim();
                    const cn  = (o.combinedName || '').trim();
                    const pm  = cn.match(/^(.+?)\s*\(([^)]+)\)\s*$/);
                    const fid = pm ? pm[2].trim() : oid;
                    return fid === fvId || oid === fvId || cn === fvId || (cn && cn.indexOf('(' + fvId + ')') >= 0);
                });
                if (!opt) {
                    actions.push({field: 'add_' + fvId, ok: false, error: 'field_not_in_available'});
                    return;
                }
                const entry = Object.assign({}, opt);
                entry.value1     = fv.value1 !== undefined ? String(fv.value1) : '';
                entry.value2     = fv.value2 !== undefined ? String(fv.value2) : '';
                entry.showInput2 = !!fv.showInput2;
                vm.selectedList.push(entry);
                actions.push({field: 'add_' + fvId, value: entry.combinedName || fvId, ok: true});
            });

            /* Digest so Angular starts rendering cuic-filter elements */
            try { iffScope.$apply(); } catch(e) {}
        } catch(e) {
            return {ok: false, error: e.message, actions};
        }
    }

    return {ok: true, actions};
}'''

# ── Field filter Pass 2: set operators and values ────────────────────
# Called AFTER CUIC_MULTISTEP_APPLY_JS (stepType='field_filter') once the
# cuic-filter DOM elements have been rendered by Angular's ng-repeat.
# wizard.py waits for 'cuic-filter' elements to appear before calling this.
#
# fieldsToApply = [{fieldId/id, operator, value1, value2, showInput2}, ...]
CUIC_FIELD_FILTER_PASS2_JS = r'''(fieldsToApply) => {
    if (typeof angular === 'undefined') return {ok: false, error: 'no_angular'};

    /* Find the visible field-filter section */
    const sections = document.querySelectorAll('filter-wizard .steps > section');
    let sec = null;
    sections.forEach(s => { if (s.style.display !== 'none') sec = s; });
    if (!sec) return {ok: false, error: 'no_visible_section'};

    const iffFields = sec.querySelector('#cuic-iff-fields');
    if (!iffFields) return {ok: false, error: 'no_iff_fields'};

    const actions = [];

    /* Find all cuic-filter elements rendered by ng-repeat="field in vm.selectedList" */
    const cfEls = iffFields.querySelectorAll('cuic-filter');
    if (!cfEls.length) return {ok: false, error: 'no_cuic_filter_elements', count: 0};

    const iffScope = angular.element(iffFields).scope();

    cfEls.forEach(cfEl => {
        try {
            /* Walk scopes to find filterCtrl — it may be on this element
               or on a child scope created by cuic-filter directive */
            let cfScope = angular.element(cfEl).scope();
            let fc = cfScope && cfScope.filterCtrl;
            if (!fc) {
                /* Try isolateScope */
                let iso = angular.element(cfEl).isolateScope();
                fc = iso && iso.filterCtrl;
            }
            if (!fc) {
                /* Walk child scopes */
                let cs = cfScope && cfScope.$$childHead;
                for (let d = 0; !fc && cs && d < 8; d++, cs = cs.$$nextSibling) {
                    fc = cs.filterCtrl;
                    if (!fc && cs.$$childHead) {
                        let cs2 = cs.$$childHead;
                        for (let d2 = 0; !fc && cs2 && d2 < 5; d2++, cs2 = cs2.$$nextSibling) {
                            fc = cs2.filterCtrl;
                        }
                    }
                }
            }
            if (!fc || !fc.filterField) {
                actions.push({field: 'unknown', ok: false, error: 'no_filterCtrl'});
                return;
            }

            /* Match this row back to its saved settings by combinedName / fieldId */
            const cn = (fc.filterField.combinedName || '').trim();
            const pm = cn.match(/^(.+?)\s*\(([^)]+)\)\s*$/);
            const rowFieldId = pm ? pm[2].trim()
                                 : (fc.filterField.fieldId || fc.filterField.id
                                    || fc.filterField.name || cn);
            const fv = fieldsToApply.find(f => {
                const fvId = (f.fieldId || f.id || '').trim();
                return fvId === rowFieldId
                    || cn === fvId
                    || (cn && cn.indexOf('(' + fvId + ')') >= 0);
            });
            if (!fv) {
                actions.push({field: rowFieldId, ok: false, error: 'no_saved_match'});
                return;
            }

            /* Resolve saved operator string to the actual option object
               from filterCtrl.options[filterType] so csSelect renders correctly */
            const rawOp = fv.operator !== undefined ? fv.operator : '';
            if (rawOp) {
                const ft     = fc.filterField.filterType;
                const opOpts = (fc.options && ft) ? (fc.options[ft] || []) : [];
                const opMatch = opOpts.find(o =>
                    (o.operator || o.value || o.id || '') === rawOp ||
                    (o.label || o.name || '') === rawOp);
                if (opMatch) {
                    fc.filterField.selected = opMatch;
                    actions.push({field: 'op_' + rowFieldId, value: rawOp, ok: true});
                } else {
                    /* Fallback: minimal object */
                    fc.filterField.selected = {operator: rawOp, label: rawOp};
                    actions.push({field: 'op_' + rowFieldId, value: rawOp, ok: false,
                                  error: 'operator_not_in_options',
                                  available: opOpts.map(o => o.operator || o.value || ''),
                                  filterType: ft || 'unknown'});
                }
            }

            /* Set value1/value2 through filterCtrl for reliable binding */
            if (fv.value1 !== undefined) {
                fc.filterField.value1 = String(fv.value1);
                actions.push({field: 'val_' + rowFieldId, value: fv.value1, ok: true});
            }
            if (fv.value2 !== undefined) fc.filterField.value2 = String(fv.value2);
            if (fv.showInput2 !== undefined) fc.filterField.showInput2 = !!fv.showInput2;

        } catch(e) {
            actions.push({field: 'err', error: e.message, ok: false});
        }
    });

    /* Final digest to update the UI */
    try { iffScope.$apply(); } catch(e) {}

    return {ok: true, actions, count: cfEls.length};
}'''


# Fallback: generic HTML form reader (non-CUIC wizards)
GENERIC_WIZARD_READ_JS = r'''() => {
    const fields = [];
    document.querySelectorAll('select').forEach(sel => {
        if (!sel.offsetParent && sel.offsetWidth === 0) return;
        const label = _findLabel(sel);
        const options = Array.from(sel.options).map(o => ({value: o.value, text: o.textContent.trim(), selected: o.selected}));
        fields.push({type:'select', label, id:sel.id, name:sel.name, options, value:Array.from(sel.selectedOptions).map(o=>o.value), multiple:sel.multiple});
    });
    document.querySelectorAll('input').forEach(inp => {
        if (!inp.offsetParent && inp.offsetWidth === 0) return;
        const t = (inp.type||'text').toLowerCase();
        if (['hidden','button','submit','reset','image'].includes(t)) return;
        const label = _findLabel(inp);
        fields.push({type:t==='checkbox'?'checkbox':t==='radio'?'radio':'text', inputType:t,
                     label, id:inp.id, name:inp.name,
                     value:inp.type==='checkbox'||inp.type==='radio'?inp.checked:inp.value,
                     placeholder:inp.placeholder||''});
    });
    document.querySelectorAll('textarea').forEach(ta => {
        if (!ta.offsetParent && ta.offsetWidth === 0) return;
        fields.push({type:'textarea', label:_findLabel(ta), id:ta.id, name:ta.name, value:ta.value});
    });
    return fields.length ? fields : null;

    function _findLabel(el) {
        if (el.id) { const lb = document.querySelector('label[for="'+el.id+'"]'); if (lb) return lb.textContent.trim(); }
        const p = el.closest('label'); if (p) return p.textContent.trim();
        let sib = el.previousElementSibling;
        if (sib && sib.textContent.trim()) return sib.textContent.trim();
        return el.name || el.id || '';
    }
}'''  # noqa: E501

# JavaScript injected into the frame to extract ALL data via ag-grid's
# internal API.  This bypasses virtual scrolling (DOM only renders
# visible rows) and is far more reliable than CSS-selector scraping.
#
# Access patterns tried (in order):
#   1. gridOptions.api  – most ag-grid versions expose this
#   2. __agComponent    – ag-grid enterprise internal
#   3. Angular scope    – AngularJS wrapper ($scope.gridApi)
#   4. ag-Grid global   – older builds register on window
AG_GRID_JS = r'''() => {
    function isVisible(el) {
        return !!el &&
            !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) &&
            window.getComputedStyle(el).visibility !== 'hidden';
    }

    /* ── locate the grid API ────────────────────────────────── */
    function findApi() {
        const roots = document.querySelectorAll(
            '.ag-root-wrapper, .ag-root, [class*="ag-theme"]'
        );

        for (const el of roots) {
            if (!isVisible(el)) continue;
            if (el.__agComponent && el.__agComponent.gridApi)
                return el.__agComponent.gridApi;
            if (el.gridOptions && el.gridOptions.api)
                return el.gridOptions.api;
        }

        for (const el of roots) {
            if (el.__agComponent && el.__agComponent.gridApi)
                return el.__agComponent.gridApi;
            if (el.gridOptions && el.gridOptions.api)
                return el.gridOptions.api;
        }

        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.__agComponent && el.__agComponent.gridApi)
                return el.__agComponent.gridApi;
        }

        if (typeof angular !== 'undefined') {
            const agEl = Array.from(document.querySelectorAll('.ag-root-wrapper, .ag-root'))
                .find(isVisible) || document.querySelector('.ag-root-wrapper, .ag-root');
            if (agEl) {
                const scope = angular.element(agEl).scope();
                if (scope && scope.gridApi) return scope.gridApi;
                if (scope && scope.gridOptions && scope.gridOptions.api)
                    return scope.gridOptions.api;
            }
        }

        if (window.gridApi) return window.gridApi;
        if (window.gridOptions && window.gridOptions.api)
            return window.gridOptions.api;
        return null;
    }

    /* ── locate column definitions ──────────────────────────── */
    function getDisplayedColumns(api) {
        try {
            const cols = api.getColumns ? api.getColumns() :
                         api.columnModel ? api.columnModel.getColumns() :
                         null;
            if (cols && cols.length) return cols;
        } catch(e) {}

        try {
            const colApi = api.columnApi || api.columnController;
            if (colApi) {
                const cols = colApi.getAllDisplayedColumns
                    ? colApi.getAllDisplayedColumns()
                    : colApi.getAllColumns();
                if (cols && cols.length) return cols;
            }
        } catch(e) {}

        try {
            const cols = api.getAllDisplayedColumns();
            if (cols && cols.length) return cols;
        } catch(e) {}

        return null;
    }

    function getColumns(api) {
        const cols = getDisplayedColumns(api);
        if (!cols || !cols.length) return null;
        return cols.map(c => ({
            field: c.colDef ? c.colDef.field || '' : c.field || '',
            headerName: c.colDef ? c.colDef.headerName || '' : c.headerName || ''
        }));
    }

    function getColumnField(col) {
        return col && col.colDef ? col.colDef.field || '' :
               col && col.field ? col.field : '';
    }

    function getColumnValue(api, col, node) {
        try {
            if (api.getValue) return api.getValue(col, node);
        } catch(e) {}

        const field = getColumnField(col);
        if (!field) return '';

        if (node.data && Object.prototype.hasOwnProperty.call(node.data, field))
            return node.data[field];

        if (node.aggData) {
            if (Object.prototype.hasOwnProperty.call(node.aggData, field))
                return node.aggData[field];
            const aggKey = Object.keys(node.aggData)
                .find(k => k === field || k.startsWith(field + '_'));
            if (aggKey) return node.aggData[aggKey];
        }

        return '';
    }

    /* ── get row-group (category) columns ──────────────────── */
    function getRowGroupCols(api) {
        const tryFns = [
            () => api.getRowGroupColumns && api.getRowGroupColumns(),
            () => api.columnApi && api.columnApi.getRowGroupColumns && api.columnApi.getRowGroupColumns(),
            () => {
                const go = api.gridOptions || (api.gridOptionsService && api.gridOptionsService.gridOptions);
                if (go && go.columnDefs) {
                    const rgcs = go.columnDefs.filter(c => c.rowGroup || c.rowGroupIndex != null);
                    return rgcs.length ? rgcs : null;
                }
            }
        ];
        for (const fn of tryFns) {
            try {
                const rgc = fn();
                if (rgc && rgc.length)
                    return rgc.map(c => ({
                        field:      (c.colDef || c).field      || '',
                        headerName: (c.colDef || c).headerName || ''
                    }));
            } catch(e) {}
        }
        return [];
    }

    /* ── extract all row data ───────────────────────────────── */
    function getRows(api, displayCols) {
        const rows = [];
        const groupFields = [];

        function resolveGroupField(node) {
            if (node.field) return node.field;
            if (node.rowGroupColumn) {
                const cd = node.rowGroupColumn.colDef || node.rowGroupColumn;
                if (cd.field) return cd.field;
            }
            if (node.groupData) {
                const k = Object.keys(node.groupData)[0];
                if (k) return k;
            }
            return '';
        }

        function getGroupPath(node) {
            const path = [];
            for (let current = node; current; current = current.parent) {
                if (!current.group) continue;
                const gField = resolveGroupField(current);
                if (!gField || current.key == null) continue;
                if (!groupFields.includes(gField)) groupFields.push(gField);
                path.unshift({ field: gField, key: current.key, level: current.level });
            }
            return path;
        }

        function buildRow(node, flags) {
            const row = node.data ? Object.assign({}, node.data) : {};
            const path = getGroupPath(node);

            for (const segment of path) {
                if (!row[segment.field]) row[segment.field] = segment.key;
            }

            for (const col of displayCols) {
                const field = getColumnField(col);
                if (!field) continue;
                if (Object.prototype.hasOwnProperty.call(row, field) && row[field] !== '')
                    continue;
                const value = getColumnValue(api, col, node);
                if (value != null && value !== '') row[field] = value;
            }

            if (path.length) row.__groupPath = path;
            return Object.assign(row, flags || {});
        }

        try {
            api.forEachNode(node => {
                if (node.group) {
                    rows.push(buildRow(node, {
                        __isGroupNode: true,
                        __groupLevel: node.level,
                        __isLeafGroup: !!node.leafGroup
                    }));
                    return;
                }
                if (!node.data) return;
                rows.push(buildRow(node));
            });
        } catch(e) {
            try {
                const model = api.getModel();
                model.forEachNode(node => {
                    if (node.group) {
                        rows.push(buildRow(node, {
                            __isGroupNode: true,
                            __groupLevel: node.level,
                            __isLeafGroup: !!node.leafGroup
                        }));
                    } else if (node.data) {
                        rows.push(buildRow(node));
                    }
                });
            } catch(e2) {}
        }

        try {
            const bCount = api.getPinnedBottomRowCount
                ? api.getPinnedBottomRowCount() : 0;
            for (let i = 0; i < bCount; i++) {
                const n = api.getPinnedBottomRow(i);
                if (n) rows.push(buildRow(n, { __isPinnedBottom: true }));
            }
        } catch(e) {}
        return { rows: rows, groupFields: groupFields };
    }

    /* ── main ───────────────────────────────────────────────── */
    const api = findApi();
    if (!api) return { error: 'API_NOT_FOUND' };

    const rgCols        = getRowGroupCols(api);
    const rawDisplayCols = getDisplayedColumns(api);
    const displayCols   = getColumns(api);
    if (!displayCols || displayCols.length === 0) return { error: 'NO_COLUMNS' };

    const filteredRawDisplay = rawDisplayCols
        ? rawDisplayCols.filter(c => getColumnField(c))
        : [];

    const rowResult   = getRows(api, filteredRawDisplay);
    const rows        = rowResult.rows;
    const groupFields = rowResult.groupFields;

    if (rows.length === 0) return { error: 'NO_ROWS' };

    const dispFieldSet = new Set(displayCols.map(c => c.field));
    const groupColDefs = (groupFields.length ? groupFields : rgCols.map(c => c.field))
        .filter(f => f && !dispFieldSet.has(f))
        .map(f => {
            try {
                const colApi = api.columnApi || api;
                const col = colApi.getColumn ? colApi.getColumn(f) : null;
                const hn = col && col.colDef && col.colDef.headerName;
                return { field: f, headerName: hn || f };
            } catch(e) { return { field: f, headerName: f }; }
        });

    const filteredDisplay = displayCols.filter(c => c.field && c.field !== '');
    const cols = [...groupColDefs, ...filteredDisplay];

    return { columns: cols, rows: rows, rowCount: rows.length, groupFields: groupFields };
}'''

# ── Column definition extractor ──────────────────────────────────────────
# Lightweight variant of AG_GRID_JS — only returns column headers, no rows.
# Used during Validate Path to discover available columns.
AG_GRID_COLUMNS_JS = r'''() => {
    function findApi() {
        const roots = document.querySelectorAll(
            '.ag-root-wrapper, .ag-root, [class*="ag-theme"]'
        );
        for (const el of roots) {
            if (el.__agComponent && el.__agComponent.gridApi)
                return el.__agComponent.gridApi;
            if (el.gridOptions && el.gridOptions.api)
                return el.gridOptions.api;
        }
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.__agComponent && el.__agComponent.gridApi)
                return el.__agComponent.gridApi;
        }
        if (typeof angular !== 'undefined') {
            const agEl = document.querySelector('.ag-root-wrapper, .ag-root');
            if (agEl) {
                const scope = angular.element(agEl).scope();
                if (scope && scope.gridApi) return scope.gridApi;
                if (scope && scope.gridOptions && scope.gridOptions.api)
                    return scope.gridOptions.api;
            }
        }
        if (window.gridApi) return window.gridApi;
        if (window.gridOptions && window.gridOptions.api) return window.gridOptions.api;
        return null;
    }

    function getColumns(api) {
        try {
            const cols = api.getColumns ? api.getColumns() :
                         api.columnModel ? api.columnModel.getColumns() : null;
            if (cols && cols.length)
                return cols.map(c => ({
                    field:      c.colDef ? (c.colDef.field       || '') : (c.field       || ''),
                    headerName: c.colDef ? (c.colDef.headerName  || '') : (c.headerName  || '')
                }));
        } catch(e) {}
        try {
            const colApi = api.columnApi || api.columnController;
            if (colApi) {
                const cols = colApi.getAllDisplayedColumns
                    ? colApi.getAllDisplayedColumns() : colApi.getAllColumns();
                if (cols && cols.length)
                    return cols.map(c => ({
                        field:      c.colDef.field      || '',
                        headerName: c.colDef.headerName || ''
                    }));
            }
        } catch(e) {}
        try {
            const cols = api.getAllDisplayedColumns();
            if (cols && cols.length)
                return cols.map(c => ({
                    field:      c.colDef.field      || '',
                    headerName: c.colDef.headerName || ''
                }));
        } catch(e) {}
        return null;
    }

    function getRowGroupCols(api) {
        try {
            const colApi = api.columnApi || api;
            if (colApi.getRowGroupColumns) {
                const rgc = colApi.getRowGroupColumns();
                if (rgc && rgc.length)
                    return rgc.map(c => ({
                        field:      (c.colDef || c).field      || '',
                        headerName: (c.colDef || c).headerName || ''
                    }));
            }
        } catch(e) {}
        return [];
    }

    const api = findApi();
    if (!api) return { error: 'API_NOT_FOUND' };
    const rgCols      = getRowGroupCols(api);
    const displayCols = getColumns(api);
    if (!displayCols || displayCols.length === 0) return { error: 'NO_COLUMNS' };
    const dispFieldSet = new Set(displayCols.map(c => c.field));
    const cols = [
        ...rgCols.filter(c => c.field && !dispFieldSet.has(c.field)),
        ...displayCols
    ];
    return { columns: cols };
}'''
