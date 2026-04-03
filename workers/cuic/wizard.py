"""
CUIC Wizard
===========
Wizard field reading, filter application, and discovery for CUIC reports.
Supports both CUIC-specific (SPAB, multi-step) and generic HTML wizards.
"""

from typing import Dict, Any, List
from . import javascript
import time


def read_wizard_step_fields(worker) -> dict | None:
    """Read wizard fields. Tries CUIC multi-step first, then SPAB, then generic.
    Returns dict with 'type' key: 'cuic_multistep', 'cuic_spab', or 'generic'."""
    
    # ── Debug: check what's on the page ──
    for f in worker.page.frames:
        try:
            diag = f.evaluate(r'''() => {
                return {
                    hasAngular: typeof angular !== 'undefined',
                    hasFilterWizard: !!document.querySelector('filter-wizard'),
                    hasSpabCtrl: !!document.querySelector('[ng-controller*="spab"]'),
                    visibleSections: document.querySelectorAll('filter-wizard .steps > section').length,
                    hasModalDialog: !!document.querySelector('.modal-dialog'),
                    url: window.location.href
                };
            }''')
            worker.logger.info(f"  Page diagnostic: {diag}")
        except Exception as e:
            worker.logger.debug(f"  Diagnostic failed: {e}")
    
    # ── CUIC multi-step wizard (filter-wizard with wizardConfig.steps) ──
    for f in worker.page.frames:
        try:
            result = f.evaluate(javascript.CUIC_MULTISTEP_READ_JS)
            if result and result.get('_debug'):
                worker.logger.info(f"  Multi-step reader debug ({f.url[:60]}): {result}")
                continue
            if result and result.get('type') == 'cuic_multistep':
                worker.logger.info(f"  ✓ CUIC multi-step wizard step {result.get('stepIndex',0)+1}: "
                                 f"{len(result.get('params',[]))} param(s)")

                # ── Async scroll fallback for valuelist ──
                # If isolateScope didn't return full data, scroll the
                # virtual list in the browser to collect all items.
                for p in result.get('params', []):
                    if p.get('type') == 'cuic_valuelist' and p.get('_needsScroll'):
                        worker.logger.info(
                            f"  Valuelist '{p['label']}' needs scroll: "
                            f"{p['availableCount']}/{p['totalAvailable']}")
                        _scroll_collect_valuelist(worker, f, p)

                return result
        except Exception as e:
            worker.logger.warning(f"  Multi-step reader exception ({f.url[:60]}): {e}")
            pass

    # ── CUIC SPAB (single-step) path ──
    for f in worker.page.frames:
        try:
            result = f.evaluate(javascript.CUIC_WIZARD_READ_JS)
            if result and result.get('type') == 'cuic_spab':
                worker.logger.debug(f"  CUIC wizard: {len(result.get('params',[]))} param(s)")
                return result
        except Exception:
            pass

    # ── Generic fallback (standard HTML forms) ──
    all_fields = []
    for f in worker.page.frames:
        try:
            result = f.evaluate(javascript.GENERIC_WIZARD_READ_JS)
            if result:
                all_fields.extend(result)
        except Exception:
            pass
    return {'type': 'generic', 'fields': all_fields} if all_fields else None


def _scroll_collect_valuelist(worker, frame, param: dict):
    """Scroll the virtual-scrolled valuelist in the browser to collect
    all items when isolateScope() didn't return the full dataset.

    Mutates *param* in-place: updates availableNames, availableCount,
    and clears _needsScroll.
    """
    total_expected = param.get('totalAvailable', 0)
    collected = set(param.get('availableNames', []))

    # JS to read currently visible items + scroll info
    SCROLL_READ_JS = r'''(pane) => {
        const container = document.querySelector(
            '[ng-switch-when="VALUELIST"] [cuic-pane="' + pane + '"] .cuic-switcher-list'
        );
        if (!container) return null;
        const names = [];
        container.querySelectorAll('.cuic-switcher-name').forEach(el => {
            const n = (el.title || el.textContent || '').trim();
            if (n) names.push(n);
        });
        return {
            names: names,
            scrollTop: container.scrollTop,
            scrollHeight: container.scrollHeight,
            clientHeight: container.clientHeight
        };
    }'''

    SCROLL_SET_JS = r'''(pos) => {
        const container = document.querySelector(
            '[ng-switch-when="VALUELIST"] [cuic-pane="left"] .cuic-switcher-list'
        );
        if (container) container.scrollTop = pos;
    }'''

    try:
        max_iterations = 50
        for i in range(max_iterations):
            info = frame.evaluate(SCROLL_READ_JS, 'left')
            if not info:
                break

            for n in info.get('names', []):
                collected.add(n)

            worker.logger.debug(
                f"    Scroll iter {i}: collected={len(collected)}/{total_expected} "
                f"scrollTop={info['scrollTop']}/{info['scrollHeight']}")

            if len(collected) >= total_expected:
                break

            # Scroll down by one viewport
            new_pos = info['scrollTop'] + info['clientHeight']
            if new_pos >= info['scrollHeight']:
                break

            frame.evaluate(SCROLL_SET_JS, new_pos)
            worker.page.wait_for_timeout(150)  # let Angular digest

        # Update param in-place
        param['availableNames'] = sorted(collected)
        param['availableCount'] = len(collected)
        param['_needsScroll'] = False
        worker.logger.info(
            f"  After scrolling: {len(collected)}/{total_expected} valuelist items collected")

    except Exception as e:
        worker.logger.warning(f"  Scroll collection failed: {e}")


def find_wizard_frame(worker):
    """Find the frame containing the wizard Next/Run buttons."""
    for f in worker.page.frames:
        try:
            for sel in ['button:has-text("Next")', 'input[type="button"][value="Next"]',
                        'button:has-text("Run")',  'input[type="button"][value="Run"]']:
                btn = f.query_selector(sel)
                if btn and btn.is_visible():
                    return f
        except Exception:
            pass
    return None


def click_wizard_button(worker, btn_text: str) -> bool:
    """Click a wizard button (Next / Run / Back) in any frame.

    Uses JavaScript element.click() instead of Playwright's click() so that
    buttons at the bottom of a tall modal dialog (outside the viewport) are
    still triggered reliably.

    Special handling for 'Run': the Run/Finish button in CUIC multi-step
    wizards lives OUTSIDE the <filter-wizard> element, in a separate
    .runreport-display-flex container.  We also try calling $ctrl.finish()
    directly to ensure Angular click handlers fire.
    """
    for f in worker.page.frames:
        try:
            # Standard button search (Next, Back, and sometimes Run)
            for sel in [f'button:has-text("{btn_text}")',
                        f'input[type="button"][value="{btn_text}"]']:
                btn = f.query_selector(sel)
                if btn and btn.is_visible():
                    f.evaluate('el => el.click()', btn)
                    worker.page.wait_for_timeout(worker.timeout_short)
                    return True

            # Extra selectors for the Run/Finish button (lives outside filter-wizard)
            if btn_text.lower() == 'run':
                for sel in ['.finishButton', 'button.finishButton',
                            '[ng-click*="finish"]', '[ng-click*="Finish"]']:
                    btn = f.query_selector(sel)
                    if btn and btn.is_visible():
                        # Try $ctrl.finish() via Angular scope for reliable triggering
                        try:
                            f.evaluate('''(el) => {
                                if (typeof angular !== 'undefined') {
                                    const scope = angular.element(el).scope();
                                    let s = scope;
                                    for (let d = 0; s && d < 10; d++, s = s.$parent) {
                                        if (s.$ctrl && typeof s.$ctrl.finish === 'function') {
                                            s.$ctrl.finish();
                                            return;
                                        }
                                    }
                                }
                                el.click();
                            }''', btn)
                        except Exception:
                            f.evaluate('el => el.click()', btn)
                        worker.page.wait_for_timeout(worker.timeout_short)
                        return True
        except Exception:
            pass
    return False


def run_filter_wizard(worker, filters: dict = None) -> bool:
    """Walk through the wizard steps, applying saved filter values.

    Supported formats:
      CUIC SPAB (flat):      {"@start_date": "THISDAY", "@agent_list": "all", ...}
      CUIC multi-step:       {"step_1": {...}, "step_2": {...}, ...}
      Step-keyed generic:    {"step_1": {"field_id": val}, ...}
      Flat generic:          {"field_id": val}  (applied to every step)
    """
    try:
        worker.page.wait_for_timeout(worker.timeout_medium)  # Wizard initialization settle time
        filters = filters or {}

        # Separate metadata from actual filter values
        meta = filters.get('_meta') or {}
        clean = {k: v for k, v in filters.items() if k != '_meta'}
        is_stepped = any(k.startswith('step_') for k in clean)
        wizard_type = meta.get('type', '')

        worker.logger.info(f"  Filter wizard: type={wizard_type}, stepped={is_stepped}, "
                         f"keys={list(clean.keys())}")
        for ck, cv in clean.items():
            worker.logger.info(f"    filter[{ck}] = {cv}")

        step = 0
        max_steps = 10

        while step < max_steps:
            step += 1

            # Read current step's field structure
            step_info = read_wizard_step_fields(worker)

            if step_info:
                stype = step_info.get('type', 'generic')

                if stype == 'cuic_multistep':
                    # Multi-step CUIC: filters stored per-step
                    step_key = f'step_{step}'
                    step_vals = clean.get(step_key, {})
                    step_title = step_info.get('stepTitle', f'Step {step}')
                    pnames = [p.get('paramName','') for p in step_info.get('params',[])]
                    worker.logger.info(f"  Wizard step {step} '{step_title}' (CUIC multi): params={pnames}")
                    worker.logger.info(f"    Saved filter values for {step_key}: {step_vals}")
                    if step_vals:
                        apply_filters_to_step(worker, step_info, step_vals)
                    else:
                        worker.logger.info(f"    No saved values for {step_key} — using CUIC defaults")

                elif stype == 'cuic_spab':
                    pnames = [p.get('paramName','') for p in step_info.get('params',[])]
                    worker.logger.info(f"  Wizard step {step} (CUIC SPAB): {pnames}")
                    # CUIC SPAB uses flat param-name keys
                    apply_filters_to_step(worker, step_info, clean)

                elif is_stepped:
                    step_vals = clean.get(f'step_{step}', {})
                    fields = step_info.get('fields', [])
                    labels = [f.get('label') or f.get('id') for f in fields]
                    worker.logger.info(f"  Wizard step {step}: {len(fields)} field(s) — {labels}")
                    if step_vals:
                        apply_filters_to_step(worker, step_info, step_vals)
                else:
                    fields = step_info.get('fields', [])
                    labels = [f.get('label') or f.get('id') for f in fields]
                    worker.logger.info(f"  Wizard step {step}: {len(fields)} field(s) — {labels}")
                    if clean:
                        apply_filters_to_step(worker, step_info, clean)

                worker.page.wait_for_timeout(800)  # Post-filter-apply settle time

            # Try Next first (middle steps), then Run (last step)
            if click_wizard_button(worker, 'Next'):
                worker.logger.info(f"  Wizard: clicked Next at step {step}")
                worker.page.wait_for_timeout(worker.timeout_short)
            elif click_wizard_button(worker, 'Run'):
                worker.logger.info(f"  Wizard: clicked Run at step {step}")
                break
            else:
                worker.logger.debug(f"  Wizard step {step}: no Next/Run button")
                break

        worker.page.wait_for_timeout(worker.timeout_long)  # Report generation wait after wizard completes
        worker.logger.info("Filter wizard done")
        worker.screenshot("03_report_running")
        return True
    except Exception as e:
        worker.logger.error(f"Filter wizard failed: {e}")
        worker.screenshot("filter_error", is_step=False)
        return False


def apply_filters_to_step(worker, step_info: dict, saved_values: dict):
    """Apply filter values. Routes to CUIC Angular path or generic DOM path.
    
    Due to the complexity of CUIC filter application (especially multi-step
    wizards with datetime, valuelist, and field filters), this function is
    approximately 400 lines. It handles Angular scope manipulation for CUIC's
    custom directives.
    
    For full implementation details, see the original cuic_worker.py file.
    """
    if not step_info or not saved_values:
        return

    stype = step_info.get('type', '')

    if stype == 'cuic_spab':
        # ── CUIC SPAB: apply via Angular scope ──
        cuic_params = {k: v for k, v in saved_values.items() if not k.startswith('_')}
        if not cuic_params:
            return
        for f in worker.page.frames:
            try:
                result = f.evaluate(javascript.CUIC_WIZARD_APPLY_JS, cuic_params)
                if result and 'applied' in result:
                    for r in result['applied']:
                        status = 'OK' if r.get('ok') else 'FAIL'
                        worker.logger.info(f"    {r.get('param')}: {status} → {r.get('value','')}")
                    return
            except Exception:
                pass

    elif stype == 'cuic_multistep':
        # ── CUIC multi-step: apply via CUIC_MULTISTEP_APPLY_JS ──
        # Routes each param type (datetime / valuelist / field_filter) through
        # the centralised Angular-scope JS snippet in javascript.py.
        params = step_info.get('params', [])
        for p in params:
            pn    = p.get('paramName', '')
            ptype = p.get('type', '')
            val   = saved_values.get(pn)
            if val is None:
                continue

            worker.logger.info(f"    {pn} ({ptype}): applying {val!r}")

            # Build the cfg dict that CUIC_MULTISTEP_APPLY_JS expects
            if ptype == 'cuic_datetime':
                cfg = {
                    'stepType': 'datetime',
                    'values': {'preset': val} if isinstance(val, str) else (val or {})
                }
            elif ptype == 'cuic_valuelist':
                cfg = {
                    'stepType': 'valuelist',
                    'values': {'selectedValues': val}
                }
            elif ptype == 'cuic_field_filter':
                if not isinstance(val, list) or not val:
                    worker.logger.info(f"    {pn}: no field filters to apply")
                    continue
                cfg = {
                    'stepType': 'field_filter',
                    'values': {'fields': val}
                }
            else:
                worker.logger.warning(f"    {pn}: unknown type '{ptype}', skipping")
                continue

            # Try every frame until the JS applies successfully
            applied = False
            applied_frame = None
            for f in worker.page.frames:
                try:
                    result = f.evaluate(javascript.CUIC_MULTISTEP_APPLY_JS, cfg)
                    if result and result.get('ok'):
                        for a in result.get('actions', []):
                            status = '✓' if a.get('ok') else '✗'
                            worker.logger.info(
                                f"      {status} {a.get('field','')}: "
                                f"{a.get('matchedNames', a.get('value', a.get('error', '')))}")
                        applied = True
                        applied_frame = f
                        if ptype != 'cuic_field_filter':
                            worker.page.wait_for_timeout(300)
                        break
                    elif result and result.get('error'):
                        worker.logger.debug(f"    {pn}: frame skip: {result.get('error','')}")
                except Exception as e:
                    worker.logger.debug(f"    {pn}: frame error: {e}")
            if not applied:
                worker.logger.warning(f"    {pn}: could NOT be applied")

            # Field filter Pass 2: set operators/values after cuic-filter elements render
            if applied and ptype == 'cuic_field_filter':
                try:
                    # Wait for cuic-filter elements on the frame that Pass 1 used
                    # (elements are inside collapsed accordions so use 'attached' not 'visible')
                    applied_frame.wait_for_selector(
                        '#cuic-iff-fields cuic-filter', state='attached', timeout=3000)

                    result2 = applied_frame.evaluate(
                        javascript.CUIC_FIELD_FILTER_PASS2_JS, val)
                    if result2 and result2.get('ok'):
                        for a in result2.get('actions', []):
                            status = 'v' if a.get('ok') else 'x'
                            worker.logger.info(
                                f"      {status} {a.get('field','')}: "
                                f"{a.get('value', a.get('error', ''))}")
                    elif result2:
                        worker.logger.warning(
                            f"    {pn} pass2: {result2.get('error','')} "
                            f"(count={result2.get('count', '?')})")
                except Exception as e:
                    worker.logger.warning(f"    {pn} pass2 error: {e}")

    else:
        # ── Generic: DOM-based ──
        fields = step_info.get('fields', [])
        for field in fields:
            key = field.get('id') or field.get('name') or field.get('label', '')
            if not key:
                continue
            val = None
            for attempt in [field.get('id'), field.get('name'), field.get('label')]:
                if attempt and attempt in saved_values:
                    val = saved_values[attempt]
                    break
            if val is None:
                continue
            worker.logger.info(f"  Setting filter '{key}' = {val}")
            _set_field_value(worker, field, val)


def _set_field_value(worker, field: dict, value):
    """Set a standard form field value in the browser (generic fallback)."""
    ftype = field.get('type', 'text')
    fid = field.get('id', '')
    fname = field.get('name', '')
    for f in worker.page.frames:
        try:
            el = None
            if fid:
                el = f.query_selector(f'#{fid}')
            if not el and fname:
                el = f.query_selector(f'[name="{fname}"]')
            if not el:
                continue
            if ftype == 'select':
                if isinstance(value, list):
                    f.evaluate('''(args) => {
                        const sel = document.querySelector(args.selector);
                        if (!sel) return;
                        Array.from(sel.options).forEach(o => o.selected = args.vals.includes(o.value));
                        sel.dispatchEvent(new Event('change', {bubbles:true}));
                    }''', {'selector': f'#{fid}' if fid else f'[name="{fname}"]', 'vals': value})
                else:
                    el.select_option(str(value))
            elif ftype == 'checkbox':
                if bool(value) != field.get('value', False):
                    el.click()
            elif ftype in ('text', 'textarea'):
                el.fill(str(value))
                f.evaluate('''(sel) => {
                    const el = document.querySelector(sel);
                    if (el) { el.dispatchEvent(new Event('input',{bubbles:true}));
                              el.dispatchEvent(new Event('change',{bubbles:true})); }
                }''', f'#{fid}' if fid else f'[name="{fname}"]')
            break
        except Exception as e:
            worker.logger.debug(f"  Could not set {fid or fname}: {e}")


def _discover_columns_after_run(worker) -> dict:
    """Wait for the report grid to render after clicking Run, then extract
    column definitions using the ag-grid JS API.

    Returns:
        {
          'available':      [{headerName, field}, ...],  # all columns incl. first
          'datetime_field': str,  # field key used to detect consolidated rows
          'discovered_at':  str,  # ISO timestamp
        }
    Callers should handle empty 'available' gracefully.
    """
    import datetime as _dt
    result = {'available': [], 'datetime_field': '', 'discovered_at': ''}
    try:
        # Wait for the report page / new tab to render the grid
        worker.logger.info("  Column discovery: waiting for ag-grid to render...")
        all_pages = worker.context.pages
        target = all_pages[-1] if len(all_pages) > 1 else worker.page

        try:
            target.wait_for_selector(
                '.ag-root, .ag-body-viewport, [class*="ag-theme"], table',
                timeout=worker.timeout_long * 2  # reports can be slow
            )
        except Exception:
            worker.logger.info("  Column discovery: grid not detected within timeout, trying anyway")

        # Search every frame for ag-grid
        for frame in target.frames:
            try:
                has_ag = bool(frame.query_selector(
                    '.ag-root, .ag-body-viewport, [class*="ag-theme"]'))
            except Exception:
                continue
            if not has_ag:
                continue

            res = frame.evaluate(javascript.AG_GRID_COLUMNS_JS)
            if not isinstance(res, dict) or 'error' in res:
                worker.logger.info(f"  Column discovery frame {frame.url[:60]}: {res}")
                continue

            cols = res.get('columns', [])
            if not cols:
                continue

            worker.logger.info(f"  Column discovery: {len(cols)} columns from {frame.url[:60]}")

            # Detect the datetime field — used to identify consolidated rows.
            # A consolidated row has an empty value in the datetime column.
            # Heuristics (in order of confidence):
            #   1. Column whose headerName is exactly/closely "DateTime" (case-insensitive)
            #   2. First column whose headerName contains "date" (excluding "created", "updated")
            #   3. Fall back to the second column's field key
            dt_field = ''
            skip_words = {'created', 'updated', 'modified', 'database'}
            for c in cols:
                hn = (c.get('headerName') or '').strip().lower()
                if hn in ('datetime', 'date time', 'date/time'):
                    dt_field = c.get('field', '')
                    break
            if not dt_field:
                for c in cols:
                    hn = (c.get('headerName') or '').strip().lower()
                    if 'date' in hn and not any(sw in hn for sw in skip_words):
                        dt_field = c.get('field', '')
                        break
            if not dt_field and len(cols) > 1:
                dt_field = cols[1].get('field', '')
                worker.logger.info(
                    f"  Column discovery: datetime field not found by name, "
                    f"using second column: {dt_field!r}"
                )

            result['available'] = cols
            result['datetime_field'] = dt_field
            result['discovered_at'] = _dt.datetime.now().isoformat(timespec='seconds')
            return result

        worker.logger.warning("  Column discovery: no ag-grid frame found after Run")
    except Exception as e:
        worker.logger.warning(f"  Column discovery failed: {e}")
    return result


def discover_wizard(worker_class, report_config: dict) -> dict:
    """Open a report and read all wizard steps' fields.
    
    Returns a unified format:
      {type: 'cuic_spab' | 'cuic_multistep' | 'generic',
       steps: [{step:1, title:'...', params:[...]}],
       datePresets: [...],
       error: ''}

    For SPAB (single-step) reports, there is one step with all params.
    For multi-step wizards, each step has its own params array.
    """
    worker = worker_class()
    worker._load_config()
    folder = str(report_config.get('folder', '') or '').strip().strip('/')
    name = str(report_config.get('name', '') or '').strip().strip('/')
    result = {'steps': [], 'error': '', 'type': 'generic'}

    if not name:
        result['error'] = 'Missing CUIC report name'
        return result
    if not folder:
        result['error'] = 'Invalid CUIC report path. Use the full Folder/Report Name path.'
        return result

    try:
        worker.setup_browser(ignore_https_errors=True)

        # Import auth and navigation modules
        from . import auth, navigation

        if not auth.login(worker):
            result['error'] = 'Login failed'
            return result

        frame = navigation.get_reports_frame(worker)
        if not frame:
            result['error'] = 'Reports iframe not found'
            return result

        if not navigation.open_report(worker, frame, folder, name):
            result['error'] = f'Could not open {folder}/{name}'
            return result

        worker.page.wait_for_timeout(worker.timeout_medium)

        # Walk through wizard steps reading fields
        step = 0
        max_steps = 10
        while step < max_steps:
            step += 1
            step_info = read_wizard_step_fields(worker)

            if step_info:
                stype = step_info.get('type', 'generic')

                if stype == 'cuic_multistep':
                    # Multi-step wizard — each call returns one step
                    result['type'] = 'cuic_multistep'
                    step_params = step_info.get('params', [])
                    step_title = step_info.get('stepTitle', f'Step {step}')
                    # Collect datePresets from datetime params
                    for p in step_params:
                        if p.get('type') == 'cuic_datetime' and p.get('datePresets'):
                            result['datePresets'] = p['datePresets']
                    result['steps'].append({
                        'step': step,
                        'title': step_title,
                        'type': 'cuic_multistep',
                        'params': step_params
                    })
                    # Store step titles on first discovery
                    if 'stepTitles' not in result:
                        result['stepTitles'] = step_info.get('stepTitles', [])

                elif stype == 'cuic_spab':
                    # SPAB single-step wizard — all params on one page
                    result['type'] = 'cuic_spab'
                    result['params'] = step_info.get('params', [])
                    result['datePresets'] = step_info.get('datePresets', [])
                    result['steps'].append({
                        'step': step,
                        'title': 'Parameters',
                        'type': 'cuic_spab',
                        'params': step_info.get('params', [])
                    })
                else:
                    # Generic HTML fields
                    result['steps'].append({
                        'step': step,
                        'title': f'Step {step}',
                        'fields': step_info.get('fields', [])
                    })

            # Check for Run (last step) — but NOT Next+Run (intermediate)
            has_run = False
            has_next = False
            for f in worker.page.frames:
                try:
                    for sel in ['button:has-text("Run")', 'input[type="button"][value="Run"]']:
                        if f.query_selector(sel):
                            has_run = True
                            break
                    for sel in ['button:has-text("Next")', 'input[type="button"][value="Next"]']:
                        if f.query_selector(sel):
                            has_next = True
                            break
                except Exception:
                    pass

            if has_run and not has_next:
                break

            if not click_wizard_button(worker, 'Next'):
                break

            worker.page.wait_for_timeout(worker.timeout_short)

        worker.logger.info(f"Discovery: {len(result['steps'])} wizard step(s) found, type={result['type']}")

        # ── Click Run to render the report and discover available columns ──
        worker.logger.info("Discovery: clicking Run to render the report for column discovery...")
        run_clicked = click_wizard_button(worker, 'Run')
        if not run_clicked:
            worker.logger.warning("Discovery: could not click Run — column discovery skipped")
        else:
            result['_columns_meta'] = _discover_columns_after_run(worker)
            worker.logger.info(
                f"Discovery: columns_meta={{"
                f"columns:{len(result['_columns_meta'].get('available', []))}, "
                f"datetime_field:{result['_columns_meta'].get('datetime_field')!r}}}"
            )
            # Close the report tab so logout can proceed cleanly
            navigation.close_report_page(worker)

        return result

    except Exception as e:
        result['error'] = str(e)
        return result
    finally:
        # Import auth module for logout
        from . import auth
        logout_ok = auth.logout(worker)
        
        if logout_ok:
            # Small delay so logout screen is visible when headless=false
            if worker.page and not worker.page.is_closed():
                worker.page.wait_for_timeout(1500)
        else:
            # Logout failed — keep browser open for manual intervention
            worker.logger.error("")
            worker.logger.error("="*60)
            worker.logger.error("⚠⚠⚠ KEEPING BROWSER OPEN FOR 60 SECONDS ⚠⚠⚠")
            worker.logger.error("Please manually logout:")
            worker.logger.error("1. Click the user menu (top right)")
            worker.logger.error("2. Click 'Sign Out'")
            worker.logger.error("Or visit: https://148.151.32.77:8444/cuicui/Logout.jsp")
            worker.logger.error("="*60)
            if worker.page and not worker.page.is_closed():
                worker.page.wait_for_timeout(60000)  # 60 seconds
        
        worker.teardown_browser()
