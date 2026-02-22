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
        let dtScope;
        try { dtScope = angular.element(dtFilter).scope(); } catch(e) {}
        if (dtScope) {
            /* Read the heading text for label */
            const heading = sec.querySelector('.accordion--navigation a');
            const label = heading ? heading.textContent.replace(/[^a-zA-Z0-9_ ()]/g,'').trim() : 'DateTime';

            /* Date preset options */
            const datePresets = [];
            const selEl = dtFilter.querySelector('.csSelect-container');
            if (selEl) {
                try {
                    const selScope = angular.element(selEl).scope();
                    const opts = selScope?.csSelect?.options || selScope?.sel?.options || [];
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

            /* Days section — hidden by ng-hide when preset is THISDAY or LASTDAY
               ng-hide="dateTimeField.relativeRange=='THISDAY'||dateTimeField.relativeRange=='LASTDAY'" */
            const hasDays       = (relativeRange !== 'THISDAY' && relativeRange !== 'LASTDAY');
            const allDayChecked = cfg.allDayChecked || 'true';   /* 'true'=All Day, 'false'=Custom */
            /* daysKey = ['mon','tue','wed','thu','fri','sat','sun'] on the scope */
            const daysKey = dtScope.daysKey || ['mon','tue','wed','thu','fri','sat','sun'];
            const days = {};
            daysKey.forEach(d => { days[d] = dtField[d] || ''; }); /* 'checked' or '' */

            /* Special report-linking modes */
            const isMatchField     = !!(dtScope.hcfCtrl?.isMatchField);
            const isMatchDateRange = !!(dtScope.hcfCtrl?.isMatchDateRange);

            result.params.push({
                dataType:         filterType,
                type:             'cuic_datetime',
                label:            label,
                paramName:        label,
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
            const iffScope = angular.element(iffFields).scope();
            if (iffScope && iffScope.vm && iffScope.vm.selectedList) {
                /* Try to collect operator options from any visible operator csSelect */
                const opSelEl = iffFields.querySelector('.csSelect-container');
                if (opSelEl) {
                    try {
                        const opSelScope = angular.element(opSelEl).scope();
                        const opts = opSelScope?.csSelect?.options || [];
                        opts.forEach(o => availableOperators.push({
                            value: o.value || o.id || '',
                            label: o.label || o.name || o.value || ''
                        }));
                    } catch(e) {}
                }
                iffScope.vm.selectedList.forEach(f => {
                    const cn  = (f.combinedName || '').trim();
                    const pm  = cn.match(/^(.+?)\\s*\\(([^)]+)\\)\\s*$/);
                    const fid = pm ? pm[2].trim() : (f.id || f.name || f.fieldName || cn);
                    const lbl = pm ? pm[1].trim() : cn;
                    selectedFieldIds.push(fid);
                    /* operator may be a string key (e.g. 'EQ') or an object {value, label} */
                    let op = f.operator;
                    if (op && typeof op === 'object') op = op.value || op.id || String(op);
                    selectedFields.push({
                        fieldId:    fid,
                        label:      lbl,
                        operator:   op   || '',
                        value1:     f.value1  !== undefined ? String(f.value1)  : '',
                        value2:     f.value2  !== undefined ? String(f.value2)  : '',
                        showInput2: !!f.showInput2
                    });
                });
            }
        } catch(e) {}

        result.params.push({
            dataType:           'FIELD_FILTER',
            type:               'cuic_field_filter',
            label:              'Field Filters',
            paramName:          '_field_filters',
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

        const p = {dataType: item.dataType, label, paramName, paramName2,
                   isRequired: !!item.isRequired};

        switch (item.dataType) {
            case 'DATETIME':
            case 'DATE':
                p.type = 'cuic_datetime';
                p.datePresets = datePresets;
                p.currentPreset = (item.date1 && item.date1.dropDownSelected)
                    ? item.date1.dropDownSelected.value : '';
                p.hasDateRange = !!item.date2;
                /* current date values */
                if (item.date1 && item.date1.dateValue)
                    p.currentDate1 = item.date1.dateValue;
                if (item.date2 && item.date2.dateValue)
                    p.currentDate2 = item.date2.dateValue;
                /* time range */
                p.allTime = item.allTime || 1;
                p.hasTimeRange = (item.dataType !== 'DATE' && !!item.date2);
                if (item.time1 && item.time1.dateValue)
                    p.currentTime1 = item.time1.dateValue;
                if (item.time2 && item.time2.dateValue)
                    p.currentTime2 = item.time2.dateValue;
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

    return {type: 'cuic_spab', params, datePresets};
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
                       or an object: {preset, date1, date2, allTime, time1, time2} */
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
                    if (cfg.allTime !== undefined)
                        item.allTime = cfg.allTime;
                    if (cfg.allTime === 2) {
                        if (cfg.time1 && item.time1) {
                            const t = new Date(cfg.time1);
                            if (!isNaN(t)) item.time1.dateValue = t;
                        }
                        if (cfg.time2 && item.time2) {
                            const t = new Date(cfg.time2);
                            if (!isNaN(t)) item.time2.dateValue = t;
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
                            /* fallback: flatten and move all */
                            function flattenAll(list) {
                                const out = [];
                                (list||[]).forEach(v => {
                                    if (v.children && v.children.length)
                                        out.push(...flattenAll(v.children));
                                    else out.push(v);
                                });
                                return out;
                            }
                            item.rvaluelist = (item.rvaluelist || [])
                                .concat(flattenAll(item.lvaluelist));
                            item.lvaluelist = [];
                        }
                        results.push({param: paramName, ok: true, value: 'all'});
                    } else if (Array.isArray(val) && val.length) {
                        /* move specific items by name (search recursively) */
                        function extractByName(list, names) {
                            const matched = [], rest = [];
                            (list||[]).forEach(v => {
                                if (v.children && v.children.length) {
                                    const [m, r] = [[], []];
                                    v.children.forEach(ch => {
                                        if (names.includes(ch.name)) m.push(ch);
                                        else r.push(ch);
                                    });
                                    matched.push(...m);
                                    if (r.length) {
                                        const copy = Object.assign({}, v, {children: r});
                                        rest.push(copy);
                                    }
                                } else {
                                    if (names.includes(v.name)) matched.push(v);
                                    else rest.push(v);
                                }
                            });
                            return [matched, rest];
                        }
                        const [toMove, remaining] = extractByName(item.lvaluelist, val);
                        item.lvaluelist = remaining;
                        item.rvaluelist = (item.rvaluelist || []).concat(toMove);
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
        let scope;
        try { scope = angular.element(dtFilter).scope(); }
        catch(e) { return {ok: false, error: e.message}; }
        if (!scope) return {ok: false, error: 'no_scope'};

        try {
            /* ── Preset / date range dropdown ── */
            if (vals.preset !== undefined) {
                const selEl = dtFilter.querySelector('.csSelect-container');
                if (selEl) {
                    const selScope = angular.element(selEl).scope();
                    const opts = selScope?.csSelect?.options || scope.sel?.options || [];
                    const opt  = opts.find(o =>
                        (o.value || o.id || '') === vals.preset ||
                        (o.label || o.name  || '') === vals.preset);
                    if (opt) {
                        scope.relativeRangeSelected = opt;
                        if (selScope && selScope.csSelect) selScope.csSelect.selected = opt;
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
                if (swIso && Array.isArray(swIso.leftModel)) {
                    const [toMove, remaining] = extractByName(swIso.leftModel, vals.selectedValues);
                    swIso.leftModel  = remaining;
                    swIso.rightModel = (swIso.rightModel||[]).concat(toMove);
                    try { swIso.$apply(); } catch(e) {}
                    actions.push({field: 'selectedValues', count: toMove.length,
                                  method: 'switcher_iso', ok: true});
                } else {
                    const fc = findFilterCtrl();
                    if (fc && fc.filterField) {
                        const [toMove, remaining] = extractByName(
                            fc.leftAttributes||[], vals.selectedValues);
                        fc.leftAttributes    = remaining;
                        fc.filterField.value = (fc.filterField.value||[]).concat(toMove);
                        const cf2 = sec.querySelector('cuic-filter');
                        try { if(cf2) angular.element(cf2).scope().$apply(); } catch(e) {}
                        actions.push({field: 'selectedValues', count: toMove.length,
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
    else if (cfg.stepType === 'field_filter') {
        const iffFields = sec.querySelector('#cuic-iff-fields');
        if (!iffFields) return {ok: false, error: 'no_iff_fields'};

        try {
            const iffScope = angular.element(iffFields).scope();
            if (!iffScope || !iffScope.vm || !iffScope.vm.selectedList)
                return {ok: false, error: 'no_vm_selectedList'};

            /* vals.fields = [{fieldId|id, operator, value1, value2}, ...] */
            (vals.fields || []).forEach(fv => {
                const fvId = (fv.fieldId || fv.id || '').trim();
                const item = iffScope.vm.selectedList.find(f => {
                    const cn  = (f.combinedName || '').trim();
                    const pm  = cn.match(/^(.+?)\s*\(([^)]+)\)\s*$/);
                    const fid = pm ? pm[2].trim() : cn;
                    return fid === fvId || cn === fvId;
                });
                if (!item) {
                    actions.push({field: 'operator_' + fvId, ok: false,
                                  error: 'field_not_in_selectedList'});
                    return;
                }
                if (fv.operator !== undefined) {
                    item.operator = fv.operator;
                    actions.push({field: 'operator_' + fvId, value: fv.operator, ok: true});
                }
                if (fv.value1 !== undefined) {
                    item.value1 = fv.value1;
                    actions.push({field: 'value1_' + fvId, value: fv.value1, ok: true});
                }
                if (fv.value2 !== undefined) {
                    item.value2 = fv.value2;
                    actions.push({field: 'value2_' + fvId, value: fv.value2, ok: true});
                }
            });
            try { iffScope.$apply(); } catch(e) {}
        } catch(e) {
            return {ok: false, error: e.message, actions};
        }
    }

    return {ok: true, actions};
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
    /* ── locate the grid API ────────────────────────────────── */
    function findApi() {
        // Pattern 1: walk DOM nodes for gridOptions (works on most versions)
        const roots = document.querySelectorAll(
            '.ag-root-wrapper, .ag-root, [class*="ag-theme"]'
        );
        for (const el of roots) {
            // ag-grid >= 25: element stores a reference
            if (el.__agComponent && el.__agComponent.gridApi)
                return el.__agComponent.gridApi;
            // some builds put it on gridOptions attached to the element
            if (el.gridOptions && el.gridOptions.api)
                return el.gridOptions.api;
        }
        // Pattern 2: walk ALL elements (broader search)
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.__agComponent && el.__agComponent.gridApi)
                return el.__agComponent.gridApi;
        }
        // Pattern 3: AngularJS scope
        if (typeof angular !== 'undefined') {
            const agEl = document.querySelector('.ag-root-wrapper, .ag-root');
            if (agEl) {
                const scope = angular.element(agEl).scope();
                if (scope && scope.gridApi) return scope.gridApi;
                if (scope && scope.gridOptions && scope.gridOptions.api)
                    return scope.gridOptions.api;
            }
        }
        // Pattern 4: window-level references
        if (window.gridApi) return window.gridApi;
        if (window.gridOptions && window.gridOptions.api)
            return window.gridOptions.api;
        return null;
    }

    /* ── locate column definitions ──────────────────────────── */
    function getColumns(api) {
        // Modern API (>= v28): api.getColumns()
        try {
            const cols = api.getColumns ? api.getColumns() :
                         api.columnModel ? api.columnModel.getColumns() :
                         null;
            if (cols && cols.length) {
                return cols.map(c => ({
                    field:    c.colDef ? c.colDef.field    : c.field    || '',
                    headerName: c.colDef ? c.colDef.headerName : c.headerName || ''
                }));
            }
        } catch(e) {}

        // columnApi (ag-grid < v31)
        try {
            const colApi = api.columnApi || api.columnController;
            if (colApi) {
                const cols = colApi.getAllDisplayedColumns
                    ? colApi.getAllDisplayedColumns()
                    : colApi.getAllColumns();
                if (cols && cols.length) {
                    return cols.map(c => ({
                        field: c.colDef.field || '',
                        headerName: c.colDef.headerName || ''
                    }));
                }
            }
        } catch(e) {}

        // getAllDisplayedColumns directly on api (v31+)
        try {
            const cols = api.getAllDisplayedColumns();
            if (cols && cols.length) {
                return cols.map(c => ({
                    field: c.colDef.field || '',
                    headerName: c.colDef.headerName || ''
                }));
            }
        } catch(e) {}

        return null;
    }

    /* ── extract all row data ───────────────────────────────── */
    function getRows(api) {
        const rows = [];
        try {
            // Works on all ag-grid versions
            api.forEachNode(node => {
                if (node.data) rows.push(node.data);
            });
        } catch(e) {
            // Fallback: getModel().forEachNode()
            try {
                const model = api.getModel();
                model.forEachNode(node => {
                    if (node.data) rows.push(node.data);
                });
            } catch(e2) {}
        }
        return rows;
    }

    /* ── main ───────────────────────────────────────────────── */
    const api = findApi();
    if (!api) return { error: 'API_NOT_FOUND' };

    const cols = getColumns(api);
    if (!cols || cols.length === 0) return { error: 'NO_COLUMNS' };

    const rows = getRows(api);
    if (rows.length === 0) return { error: 'NO_ROWS' };

    return { columns: cols, rows: rows, rowCount: rows.length };
}'''
