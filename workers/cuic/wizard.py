"""
CUIC Wizard
===========
Wizard field reading, filter application, and discovery for CUIC reports.
Supports both CUIC-specific (SPAB, multi-step) and generic HTML wizards.
"""

from copy import deepcopy
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


_MISSING = object()


def _unique_nonempty(values: List[Any]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values or []:
        normalized = str(value or '').strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _cuic_param_aliases(param: dict) -> List[str]:
    return _unique_nonempty([
        param.get('storageKey'),
        *(param.get('aliases') or []),
        param.get('paramName'),
        param.get('paramName2'),
        param.get('label'),
    ])


def _cuic_param_key(param: dict) -> str:
    aliases = _cuic_param_aliases(param)
    return aliases[0] if aliases else ''


def _resolve_saved_cuic_value(saved_values: dict, param: dict, default=_MISSING):
    source = saved_values or {}
    for alias in _cuic_param_aliases(param):
        if alias in source:
            return source[alias]
    return default


def _normalize_field_filter_entries(value: Any) -> List[dict]:
    if not isinstance(value, list):
        return []
    normalized: List[dict] = []
    for item in value:
        if isinstance(item, str):
            field_id = item.strip()
            if not field_id:
                continue
            normalized.append({
                'id': field_id,
                'fieldId': field_id,
                'operator': '',
                'value1': '',
                'value2': '',
                'showInput2': False,
            })
            continue
        if not isinstance(item, dict):
            continue
        field_id = str(item.get('fieldId') or item.get('id') or item.get('label') or '').strip()
        if not field_id:
            continue
        normalized.append({
            **item,
            'id': field_id,
            'fieldId': field_id,
            'operator': str(item.get('operator') or ''),
            'value1': str(item.get('value1')) if item.get('value1') is not None else '',
            'value2': str(item.get('value2')) if item.get('value2') is not None else '',
            'showInput2': bool(item.get('showInput2')),
        })
    return normalized


def _normalize_datetime_expected(value: Any) -> dict:
    if isinstance(value, str):
        return {'preset': value}
    if not isinstance(value, dict):
        return {}
    normalized = dict(value)
    if 'preset' not in normalized and normalized.get('currentPreset'):
        normalized['preset'] = normalized.get('currentPreset')
    return normalized


def _normalize_discovery_mode(value: Any) -> str:
    mode = str(value or '').strip().lower()
    if mode in ('discover_columns', 'columns', 'column_discovery', 'with_columns'):
        return 'discover_columns'
    return 'schema_only'


def _normalize_discovery_filters(filters: Any) -> dict:
    return deepcopy(filters) if isinstance(filters, dict) else {}


def _cuic_value_is_configured(value: Any, param_type: str) -> bool:
    if value is _MISSING or value is None:
        return False

    if param_type == 'cuic_valuelist':
        return value == 'all' or (isinstance(value, list) and len(value) > 0)

    if param_type == 'cuic_field_filter':
        return len(_normalize_field_filter_entries(value)) > 0

    if param_type == 'cuic_datetime':
        normalized = _normalize_datetime_expected(value)
        return bool(
            normalized.get('preset')
            or normalized.get('currentPreset')
            or normalized.get('date1')
            or normalized.get('date2')
        )

    if isinstance(value, str):
        return bool(value.strip())

    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0

    return True


def _current_datetime_value_from_param(param: dict) -> Any:
    current_preset = str(param.get('currentPreset') or '').strip()
    if not current_preset:
        return _MISSING

    if current_preset != 'CUSTOM':
        return current_preset

    value = {
        'preset': current_preset,
        'date1': str(param.get('currentDate1') or ''),
        'date2': str(param.get('currentDate2') or ''),
        'time1': str(param.get('currentTime1') or ''),
        'time2': str(param.get('currentTime2') or ''),
        'allTimeChecked': str(param.get('allTimeChecked') or ''),
        'allDayChecked': str(param.get('allDayChecked') or ''),
        'days': deepcopy(param.get('days') or {}),
    }
    if _cuic_value_is_configured(value, 'cuic_datetime'):
        return value
    return _MISSING


def _pick_discovery_datetime_value(param: dict) -> tuple[Any, str]:
    current_value = _current_datetime_value_from_param(param)
    if current_value is not _MISSING:
        return current_value, 'used the current CUIC date preset'

    for preset in param.get('datePresets') or []:
        preset_value = str((preset or {}).get('value') or '').strip()
        if not preset_value or preset_value == 'CUSTOM':
            continue
        return preset_value, f"selected preset {preset_value!r} for discovery"

    return _MISSING, 'no safe non-custom date preset was available'


def _summarize_discovery_value(param_type: str, value: Any) -> str:
    if param_type == 'cuic_valuelist':
        values = [str(v) for v in (value or [])[:3]]
        suffix = '...' if isinstance(value, list) and len(value) > 3 else ''
        return ', '.join(values) + suffix

    if param_type == 'cuic_datetime':
        normalized = _normalize_datetime_expected(value)
        return str(normalized.get('preset') or normalized.get('date1') or '')

    if param_type == 'cuic_field_filter':
        fields = [entry.get('fieldId') or entry.get('id') or '' for entry in _normalize_field_filter_entries(value)]
        fields = [field for field in fields if field]
        suffix = '...' if len(fields) > 3 else ''
        return ', '.join(fields[:3]) + suffix

    return str(value)


def _pick_discovery_value(param: dict) -> tuple[Any, str]:
    param_type = str(param.get('type') or '')

    if param_type == 'cuic_valuelist':
        selected_values = _unique_nonempty(param.get('selectedValues') or [])
        if selected_values:
            return selected_values, 'used the current CUIC selection'

        available_names = _unique_nonempty(param.get('availableNames') or [])
        if available_names:
            return [available_names[0]], 'selected the first available value for discovery'

        return _MISSING, 'no available values were exposed by CUIC'

    if param_type == 'cuic_datetime':
        return _pick_discovery_datetime_value(param)

    if param_type == 'cuic_field_filter':
        selected_fields = _normalize_field_filter_entries(param.get('selectedFields'))
        if selected_fields:
            return selected_fields, 'used the current CUIC field filter selection'

        selected_field_ids = _normalize_field_filter_entries(param.get('selectedFieldIds'))
        if selected_field_ids:
            return selected_field_ids, 'used the current CUIC field filter selection'

        return _MISSING, 'required field filters need manual values before discovery can run'

    return _MISSING, 'this required parameter type does not have an automatic discovery fallback'


def _record_column_discovery_blocker(blockers: List[dict], param: dict, reason: str, step_key: str = '', step_title: str = ''):
    blockers.append({
        'step': step_key,
        'title': step_title,
        'label': param.get('label') or _cuic_param_key(param) or param.get('paramName') or 'Unknown parameter',
        'paramKey': _cuic_param_key(param),
        'type': param.get('type') or '',
        'reason': reason,
    })


def _remove_unconfigured_field_filter_values(container: dict, params: List[dict]):
    if not isinstance(container, dict):
        return

    for param in params or []:
        if str(param.get('type') or '') != 'cuic_field_filter':
            continue

        current_value = _resolve_saved_cuic_value(container, param)
        if _cuic_value_is_configured(current_value, 'cuic_field_filter'):
            continue

        for alias in _cuic_param_aliases(param):
            container.pop(alias, None)


def _fill_required_discovery_params(container: dict, params: List[dict], auto_filled: List[dict], blockers: List[dict], *, step_key: str = '', step_title: str = ''):
    for param in params or []:
        param_type = str(param.get('type') or '')
        current_value = _resolve_saved_cuic_value(container, param)

        if param_type == 'cuic_field_filter' and not _cuic_value_is_configured(current_value, param_type):
            continue

        if not param.get('isRequired'):
            continue

        if _cuic_value_is_configured(current_value, param_type):
            continue

        param_key = _cuic_param_key(param)
        if not param_key:
            _record_column_discovery_blocker(blockers, param, 'parameter has no stable storage key', step_key, step_title)
            continue

        discovery_value, reason = _pick_discovery_value(param)
        if not _cuic_value_is_configured(discovery_value, param_type):
            _record_column_discovery_blocker(blockers, param, reason, step_key, step_title)
            continue

        container[param_key] = discovery_value
        auto_filled.append({
            'step': step_key,
            'title': step_title,
            'label': param.get('label') or param_key,
            'paramKey': param_key,
            'type': param_type,
            'reason': reason,
            'summary': _summarize_discovery_value(param_type, discovery_value),
        })


def _build_column_discovery_filters(discovery_result: dict, saved_filters: Any) -> tuple[dict, List[dict], List[dict]]:
    filters = _normalize_discovery_filters(saved_filters)
    auto_filled: List[dict] = []
    blockers: List[dict] = []
    discovery_type = discovery_result.get('type') or ''

    if discovery_type == 'cuic_multistep':
        if not isinstance(filters.get('_meta'), dict):
            filters['_meta'] = {
                'schemaVersion': discovery_result.get('schemaVersion') or 2,
                'type': 'cuic_multistep',
                'steps': discovery_result.get('steps') or [],
                'stepTitles': discovery_result.get('stepTitles') or [],
            }
        for step in discovery_result.get('steps') or []:
            step_number = step.get('step') or ''
            step_key = f'step_{step_number}' if step_number else ''
            step_container = filters.get(step_key)
            if not isinstance(step_container, dict):
                step_container = {}
                filters[step_key] = step_container
            _remove_unconfigured_field_filter_values(step_container, step.get('params') or [])
            _fill_required_discovery_params(
                step_container,
                step.get('params') or [],
                auto_filled,
                blockers,
                step_key=step_key,
                step_title=step.get('title') or '',
            )
        return filters, auto_filled, blockers

    if discovery_type == 'cuic_spab':
        if not isinstance(filters.get('_meta'), dict):
            filters['_meta'] = {
                'schemaVersion': discovery_result.get('schemaVersion') or 2,
                'type': 'cuic_spab',
                'params': discovery_result.get('params') or [],
            }
        params = discovery_result.get('params') or []
        _remove_unconfigured_field_filter_values(filters, params)
        _fill_required_discovery_params(filters, params, auto_filled, blockers)

    return filters, auto_filled, blockers


def _build_discovery_step_values(step_info: dict, saved_values: Any) -> tuple[dict, List[dict], List[dict]]:
    step_values = deepcopy(saved_values) if isinstance(saved_values, dict) else {}
    auto_filled: List[dict] = []
    blockers: List[dict] = []

    params = step_info.get('params') or []
    _remove_unconfigured_field_filter_values(step_values, params)
    _fill_required_discovery_params(
        step_values,
        params,
        auto_filled,
        blockers,
        step_key=str(step_info.get('step') or ''),
        step_title=step_info.get('stepTitle') or step_info.get('title') or '',
    )
    return step_values, auto_filled, blockers


def _wizard_step_signature(step_info: dict | None) -> tuple:
    if not isinstance(step_info, dict):
        return ('missing',)

    stype = str(step_info.get('type') or '')
    if stype == 'cuic_multistep':
        return (
            stype,
            str(step_info.get('stepIndex') or ''),
            str(step_info.get('stepTitle') or ''),
            tuple(_cuic_param_key(param) or param.get('paramName') or '' for param in (step_info.get('params') or [])),
        )
    if stype == 'cuic_spab':
        return (
            stype,
            tuple(_cuic_param_key(param) or param.get('paramName') or '' for param in (step_info.get('params') or [])),
        )
    return (
        stype,
        tuple((field.get('id') or field.get('name') or field.get('label') or '') for field in (step_info.get('fields') or [])),
    )


def _wizard_has_run_without_next(worker) -> bool:
    has_run = False
    has_next = False
    for frame in worker.page.frames:
        try:
            for sel in ['button:has-text("Run")', 'input[type="button"][value="Run"]']:
                if frame.query_selector(sel):
                    has_run = True
                    break
            for sel in ['button:has-text("Next")', 'input[type="button"][value="Next"]']:
                if frame.query_selector(sel):
                    has_next = True
                    break
        except Exception:
            pass
    return has_run and not has_next


def _compare_cuic_datetime(expected: Any, observed: dict) -> tuple[bool, str]:
    expected_cfg = _normalize_datetime_expected(expected)
    observed_cfg = observed or {}
    if 'allTime' in expected_cfg and 'allTimeChecked' not in expected_cfg:
        expected_cfg['allTimeChecked'] = 'false' if expected_cfg.get('allTime') == 2 else 'true'

    field_map = {
        'preset': 'currentPreset',
        'date1': 'currentDate1',
        'date2': 'currentDate2',
        'time1': 'currentTime1',
        'time2': 'currentTime2',
        'allTimeChecked': 'allTimeChecked',
        'allDayChecked': 'allDayChecked',
    }
    for expected_key, observed_key in field_map.items():
        if expected_key not in expected_cfg:
            continue
        expected_value = str(expected_cfg.get(expected_key) or '')
        observed_value = str(observed_cfg.get(observed_key) or '')
        if expected_value != observed_value:
            return False, f"{expected_key} expected {expected_value!r}, observed {observed_value!r}"

    if 'days' in expected_cfg and isinstance(expected_cfg.get('days'), dict):
        observed_days = observed_cfg.get('days') or {}
        for day_key, expected_value in expected_cfg['days'].items():
            observed_value = str(observed_days.get(day_key) or '')
            if str(expected_value or '') != observed_value:
                return False, f"day {day_key} expected {expected_value!r}, observed {observed_value!r}"

    return True, ''


def _compare_cuic_valuelist(expected: Any, observed: dict) -> tuple[bool, str]:
    observed_values = set((observed or {}).get('selectedValues') or [])
    if expected == 'all':
        total_available = int((observed or {}).get('totalAvailable') or 0)
        selected_count = len(observed_values)
        if total_available and selected_count != total_available:
            return False, f"expected all values, observed {selected_count}/{total_available} selected"
        return True, ''

    if isinstance(expected, list):
        expected_values = set(str(v) for v in expected)
        if expected_values != observed_values:
            return False, f"expected {sorted(expected_values)!r}, observed {sorted(observed_values)!r}"
    return True, ''


def _compare_cuic_field_filter(expected: Any, observed: dict) -> tuple[bool, str]:
    expected_fields = _normalize_field_filter_entries(expected)
    observed_fields = {
        entry.get('fieldId') or entry.get('id'): entry
        for entry in _normalize_field_filter_entries((observed or {}).get('selectedFields'))
    }
    observed_ids = set((observed or {}).get('selectedFieldIds') or [])

    for expected_field in expected_fields:
        field_id = expected_field.get('fieldId') or expected_field.get('id')
        if not field_id:
            continue
        if field_id not in observed_ids and field_id not in observed_fields:
            return False, f"missing field {field_id!r}"
        observed_field = observed_fields.get(field_id, {})
        for key in ('operator', 'value1', 'value2'):
            expected_value = expected_field.get(key)
            if expected_value in (None, ''):
                continue
            observed_value = str(observed_field.get(key) or '')
            if str(expected_value) != observed_value:
                return False, f"field {field_id!r} {key} expected {expected_value!r}, observed {observed_value!r}"

    return True, ''


def _verify_cuic_step_state(worker, expected_step_info: dict, saved_values: dict):
    observed_step = read_wizard_step_fields(worker)
    if not observed_step or observed_step.get('type') != expected_step_info.get('type'):
        raise ValueError('Could not re-read the current CUIC wizard step for verification')

    observed_params = {}
    for observed_param in observed_step.get('params', []):
        for alias in _cuic_param_aliases(observed_param):
            observed_params[alias] = observed_param

    mismatches = []
    for param in expected_step_info.get('params', []):
        expected_value = _resolve_saved_cuic_value(saved_values, param)
        if expected_value is _MISSING:
            continue
        observed_param = None
        for alias in _cuic_param_aliases(param):
            if alias in observed_params:
                observed_param = observed_params[alias]
                break
        if not observed_param:
            mismatches.append(f"{_cuic_param_key(param) or param.get('label')}: not found during verification")
            continue

        param_type = param.get('type', '')
        if param_type == 'cuic_datetime':
            ok, detail = _compare_cuic_datetime(expected_value, observed_param)
        elif param_type == 'cuic_valuelist':
            ok, detail = _compare_cuic_valuelist(expected_value, observed_param)
        elif param_type == 'cuic_field_filter':
            ok, detail = _compare_cuic_field_filter(expected_value, observed_param)
        else:
            observed_value = observed_param.get('currentValue')
            ok = observed_value == expected_value
            detail = f"expected {expected_value!r}, observed {observed_value!r}" if not ok else ''

        if not ok:
            mismatches.append(f"{_cuic_param_key(param) or param.get('label')}: {detail}")

    if mismatches:
        raise ValueError('CUIC step verification failed: ' + '; '.join(mismatches))


def _discovery_filters_match_observed_steps(discovery_result: dict, discovery_filters: dict) -> bool:
    if discovery_result.get('type') != 'cuic_multistep':
        return False

    clean_filters = {
        key: value
        for key, value in (discovery_filters or {}).items()
        if key != '_meta'
    }
    if not clean_filters:
        return True

    for step in discovery_result.get('steps') or []:
        step_number = step.get('step') or ''
        step_key = f'step_{step_number}' if step_number else ''
        expected_values = clean_filters.get(step_key, {})
        if not isinstance(expected_values, dict) or not expected_values:
            continue

        observed_params = {}
        for observed_param in step.get('params') or []:
            for alias in _cuic_param_aliases(observed_param):
                observed_params[alias] = observed_param

        for param in step.get('params') or []:
            expected_value = _resolve_saved_cuic_value(expected_values, param)
            if expected_value is _MISSING:
                continue

            param_type = str(param.get('type') or '')
            if not _cuic_value_is_configured(expected_value, param_type):
                continue

            observed_param = None
            for alias in _cuic_param_aliases(param):
                if alias in observed_params:
                    observed_param = observed_params[alias]
                    break

            if not observed_param:
                return False

            if param_type == 'cuic_datetime':
                ok, _ = _compare_cuic_datetime(expected_value, observed_param)
            elif param_type == 'cuic_valuelist':
                ok, _ = _compare_cuic_valuelist(expected_value, observed_param)
            elif param_type == 'cuic_field_filter':
                ok, _ = _compare_cuic_field_filter(expected_value, observed_param)
            else:
                ok = observed_param.get('currentValue') == expected_value

            if not ok:
                return False

    return True


def _run_multistep_column_discovery_on_current_wizard(worker) -> tuple[bool, str]:
    worker.page.wait_for_timeout(worker.timeout_short)
    worker.logger.info('Discovery: current wizard already has runnable values; clicking Run without reopening...')
    if not _click_run_with_retries(worker, attempts=3, wait_ms=worker.timeout_short):
        return False, 'Could not click Run on the current parameter page for column discovery.'

    worker.page.wait_for_timeout(worker.timeout_short)
    return True, ''


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


def _step_has_only_unconfigured_field_filters(step_info: dict, saved_values: dict) -> bool:
    params = step_info.get('params') or []
    if not params:
        return False

    has_field_filters = False
    for param in params:
        if str(param.get('type') or '') != 'cuic_field_filter':
            return False
        has_field_filters = True
        current_value = _resolve_saved_cuic_value(saved_values, param)
        if _cuic_value_is_configured(current_value, 'cuic_field_filter'):
            return False

    return has_field_filters


def _click_run_with_retries(worker, attempts: int = 3, wait_ms: int | None = None) -> bool:
    delay = worker.timeout_short if wait_ms is None else wait_ms
    for attempt in range(1, attempts + 1):
        if click_wizard_button(worker, 'Run'):
            return True
        if attempt != attempts:
            worker.logger.info(f"  Wizard: Run not ready yet (attempt {attempt}/{attempts})")
            worker.page.wait_for_timeout(delay)
    return False


def run_filter_wizard(worker, filters: dict = None, require_run: bool = False, *, discovery_mode: bool = False) -> bool:
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
        run_clicked = False

        while step < max_steps:
            step += 1

            # Read current step's field structure
            step_info = read_wizard_step_fields(worker)
            prefer_run = False

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
                        apply_filters_to_step(worker, step_info, step_vals, discovery_mode=discovery_mode)
                    elif discovery_mode and _step_has_only_unconfigured_field_filters(step_info, step_vals):
                        worker.logger.info(
                            "    Discovery: Field Filters has no configured values; proceeding with CUIC defaults"
                        )
                        prefer_run = True
                    else:
                        worker.logger.info(f"    No saved values for {step_key} — using CUIC defaults")

                elif stype == 'cuic_spab':
                    pnames = [p.get('paramName','') for p in step_info.get('params',[])]
                    worker.logger.info(f"  Wizard step {step} (CUIC SPAB): {pnames}")
                    # CUIC SPAB uses flat param-name keys
                    apply_filters_to_step(worker, step_info, clean, discovery_mode=discovery_mode)

                elif is_stepped:
                    step_vals = clean.get(f'step_{step}', {})
                    fields = step_info.get('fields', [])
                    labels = [f.get('label') or f.get('id') for f in fields]
                    worker.logger.info(f"  Wizard step {step}: {len(fields)} field(s) — {labels}")
                    if step_vals:
                        apply_filters_to_step(worker, step_info, step_vals, discovery_mode=discovery_mode)
                else:
                    fields = step_info.get('fields', [])
                    labels = [f.get('label') or f.get('id') for f in fields]
                    worker.logger.info(f"  Wizard step {step}: {len(fields)} field(s) — {labels}")
                    if clean:
                        apply_filters_to_step(worker, step_info, clean, discovery_mode=discovery_mode)

                worker.page.wait_for_timeout(worker.timeout_short if prefer_run else 800)

            if discovery_mode and prefer_run:
                if _click_run_with_retries(worker, attempts=3, wait_ms=worker.timeout_short):
                    worker.logger.info(f"  Wizard: clicked Run at step {step}")
                    run_clicked = True
                    break
                worker.logger.warning(
                    '  Wizard: Field Filters step did not expose Run quickly; falling back to standard button scan'
                )

            # Try Next first (middle steps), then Run (last step)
            if click_wizard_button(worker, 'Next'):
                worker.logger.info(f"  Wizard: clicked Next at step {step}")
                worker.page.wait_for_timeout(worker.timeout_short)
            elif click_wizard_button(worker, 'Run'):
                worker.logger.info(f"  Wizard: clicked Run at step {step}")
                run_clicked = True
                break
            else:
                worker.logger.debug(f"  Wizard step {step}: no Next/Run button")
                break

        if require_run and not run_clicked:
            worker.logger.error('Filter wizard did not reach the Run button')
            return False

        worker.page.wait_for_timeout(worker.timeout_long)  # Report generation wait after wizard completes
        worker.logger.info("Filter wizard done")
        worker.screenshot("03_report_running")
        return True
    except Exception as e:
        worker.logger.error(f"Filter wizard failed: {e}")
        worker.screenshot("filter_error", is_step=False)
        return False


def apply_filters_to_step(worker, step_info: dict, saved_values: dict, *, discovery_mode: bool = False):
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
        cuic_params = {}
        for param in step_info.get('params', []):
            resolved = _resolve_saved_cuic_value(saved_values, param)
            if resolved is _MISSING:
                continue
            param_name = str(param.get('paramName') or _cuic_param_key(param) or '').strip()
            if not param_name:
                continue
            if param.get('type') == 'cuic_field_filter':
                resolved = _normalize_field_filter_entries(resolved)
                if not resolved:
                    worker.logger.info(f"    {_cuic_param_key(param) or param_name}: no field filters to apply")
                    continue
            cuic_params[param_name] = resolved
        if not cuic_params:
            return
        for f in worker.page.frames:
            try:
                result = f.evaluate(javascript.CUIC_WIZARD_APPLY_JS, cuic_params)
                if result and 'applied' in result:
                    for r in result['applied']:
                        status = 'OK' if r.get('ok') else 'FAIL'
                        worker.logger.info(f"    {r.get('param')}: {status} → {r.get('value','')}")
                    _verify_cuic_step_state(worker, step_info, saved_values)
                    return
            except Exception:
                pass

    elif stype == 'cuic_multistep':
        # ── CUIC multi-step: apply via CUIC_MULTISTEP_APPLY_JS ──
        # Routes each param type (datetime / valuelist / field_filter) through
        # the centralised Angular-scope JS snippet in javascript.py.
        params = step_info.get('params', [])
        applied_any = False
        for p in params:
            pn    = p.get('paramName', '')
            ptype = p.get('type', '')
            val   = _resolve_saved_cuic_value(saved_values, p)
            if val is _MISSING:
                continue

            worker.logger.info(f"    {_cuic_param_key(p) or pn} ({ptype}): applying {val!r}")

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
                normalized_fields = _normalize_field_filter_entries(val)
                if not normalized_fields:
                    worker.logger.info(f"    {_cuic_param_key(p) or pn}: no field filters to apply")
                    continue
                cfg = {
                    'stepType': 'field_filter',
                    'values': {'fields': normalized_fields}
                }
            else:
                worker.logger.warning(f"    {_cuic_param_key(p) or pn}: unknown type '{ptype}', skipping")
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
                        applied_any = True
                        applied_frame = f
                        if ptype != 'cuic_field_filter':
                            worker.page.wait_for_timeout(300)
                        break
                    elif result and result.get('error'):
                        worker.logger.debug(f"    {_cuic_param_key(p) or pn}: frame skip: {result.get('error','')}")
                except Exception as e:
                    worker.logger.debug(f"    {_cuic_param_key(p) or pn}: frame error: {e}")
            if not applied:
                worker.logger.warning(f"    {_cuic_param_key(p) or pn}: could NOT be applied")

            # Field filter Pass 2: set operators/values after cuic-filter elements render
            if applied and ptype == 'cuic_field_filter':
                try:
                    # Wait for cuic-filter elements on the frame that Pass 1 used
                    # (elements are inside collapsed accordions so use 'attached' not 'visible')
                    applied_frame.wait_for_selector(
                        '#cuic-iff-fields cuic-filter', state='attached', timeout=3000)

                    result2 = applied_frame.evaluate(
                        javascript.CUIC_FIELD_FILTER_PASS2_JS, normalized_fields)
                    if result2 and result2.get('ok'):
                        for a in result2.get('actions', []):
                            status = 'v' if a.get('ok') else 'x'
                            worker.logger.info(
                                f"      {status} {a.get('field','')}: "
                                f"{a.get('value', a.get('error', ''))}")
                    elif result2:
                        worker.logger.warning(
                            f"    {_cuic_param_key(p) or pn} pass2: {result2.get('error','')} "
                            f"(count={result2.get('count', '?')})")
                except Exception as e:
                    worker.logger.warning(f"    {_cuic_param_key(p) or pn} pass2 error: {e}")

        if applied_any:
            _verify_cuic_step_state(worker, step_info, saved_values)

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


def _run_spab_column_discovery(worker, step_info: dict | None, discovery_filters: dict) -> tuple[bool, str]:
    """Apply SPAB discovery filters on the already open wizard and click Run.

    During schema discovery the SPAB report is already open on its parameter page.
    Reusing that live wizard is more reliable than closing and reopening the
    report again before the temporary discovery values are applied.
    """
    if not step_info or step_info.get('type') != 'cuic_spab':
        return False, 'Could not re-use the current CUIC parameter page for column discovery.'

    clean_filters = {
        key: value
        for key, value in (discovery_filters or {}).items()
        if key != '_meta'
    }

    worker.logger.info('Discovery: applying SPAB filters on the current wizard page...')
    try:
        if clean_filters:
            apply_filters_to_step(worker, step_info, clean_filters)
            _verify_cuic_step_state(worker, step_info, clean_filters)
        else:
            worker.logger.info('Discovery: SPAB report already has runnable defaults; no temporary filters needed')
    except Exception as e:
        worker.logger.warning(f'Discovery: SPAB filter apply/verify failed: {e}')
        return False, f'Could not apply discovery filters on the current parameter page: {e}'

    worker.page.wait_for_timeout(worker.timeout_short)
    worker.logger.info('Discovery: clicking Run on the current SPAB wizard...')
    if not click_wizard_button(worker, 'Run'):
        return False, 'Could not click Run on the current parameter page for column discovery.'

    worker.page.wait_for_timeout(worker.timeout_short)
    return True, ''


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
    discovery_mode = _normalize_discovery_mode(report_config.get('discovery_mode'))
    saved_filters = report_config.get('filters') if isinstance(report_config.get('filters'), dict) else {}
    result = {
        'schemaVersion': 2,
        'steps': [],
        'error': '',
        'type': 'generic',
        'discovery_mode': discovery_mode,
    }

    if not name:
        result['error'] = 'Missing CUIC report name'
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
        current_step_info = None
        while step < max_steps:
            step += 1
            step_info = read_wizard_step_fields(worker)
            step_signature = _wizard_step_signature(step_info)

            if step_info:
                current_step_info = deepcopy(step_info)
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

                    if discovery_mode == 'discover_columns':
                        step_key = f'step_{step}'
                        saved_step_values = saved_filters.get(step_key, {}) if isinstance(saved_filters, dict) else {}
                        temp_step_values, step_auto_filled, step_blockers = _build_discovery_step_values(
                            step_info,
                            saved_step_values,
                        )
                        if step_auto_filled:
                            worker.logger.info(
                                'Discovery: temporary schema values for '
                                + (step_title or step_key)
                                + ': '
                                + ', '.join(
                                    f"{entry.get('label')}: {entry.get('summary')}"
                                    for entry in step_auto_filled
                                )
                            )
                        if step_blockers:
                            result['column_discovery_blockers'] = step_blockers
                            worker.logger.warning(
                                'Discovery: current step is blocked by required params: '
                                + ', '.join(blocker.get('label', '') for blocker in step_blockers)
                            )
                            return result
                        if temp_step_values:
                            apply_filters_to_step(worker, step_info, temp_step_values, discovery_mode=True)
                            worker.page.wait_for_timeout(worker.timeout_short)

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

                    if discovery_mode == 'discover_columns':
                        temp_step_values, step_auto_filled, step_blockers = _build_discovery_step_values(
                            step_info,
                            saved_filters,
                        )
                        if step_auto_filled:
                            worker.logger.info(
                                'Discovery: temporary schema values for Parameters: '
                                + ', '.join(
                                    f"{entry.get('label')}: {entry.get('summary')}"
                                    for entry in step_auto_filled
                                )
                            )
                        if step_blockers:
                            result['column_discovery_blockers'] = step_blockers
                            worker.logger.warning(
                                'Discovery: current step is blocked by required params: '
                                + ', '.join(blocker.get('label', '') for blocker in step_blockers)
                            )
                            return result
                        if temp_step_values:
                            apply_filters_to_step(worker, step_info, temp_step_values, discovery_mode=True)
                            worker.page.wait_for_timeout(worker.timeout_short)
                else:
                    # Generic HTML fields
                    result['steps'].append({
                        'step': step,
                        'title': f'Step {step}',
                        'fields': step_info.get('fields', [])
                    })

            if _wizard_has_run_without_next(worker):
                break

            if not click_wizard_button(worker, 'Next'):
                break

            worker.page.wait_for_timeout(worker.timeout_short)
            if _wizard_has_run_without_next(worker):
                break

            next_step_info = read_wizard_step_fields(worker)
            next_signature = _wizard_step_signature(next_step_info)
            if next_signature == step_signature:
                worker.page.wait_for_timeout(worker.timeout_medium)
                next_step_info = read_wizard_step_fields(worker)
                next_signature = _wizard_step_signature(next_step_info)
                if next_signature == step_signature:
                    worker.logger.warning(
                        'Discovery: wizard did not advance after Next; stopping schema traversal on the current step'
                    )
                    break

        worker.logger.info(f"Discovery: {len(result['steps'])} wizard step(s) found, type={result['type']}")

        if discovery_mode != 'discover_columns':
            return result

        if result['type'] in ('cuic_multistep', 'cuic_spab'):
            discovery_filters, auto_filled, blockers = _build_column_discovery_filters(result, saved_filters)
            if auto_filled:
                result['auto_filled_params'] = auto_filled
            if blockers:
                result['column_discovery_blockers'] = blockers
                worker.logger.warning(
                    'Discovery: column discovery blocked by required params: '
                    + ', '.join(blocker.get('label', '') for blocker in blockers)
                )
                return result

            if result['type'] == 'cuic_spab':
                discovery_ok, discovery_error = _run_spab_column_discovery(
                    worker,
                    current_step_info,
                    discovery_filters,
                )
                if not discovery_ok:
                    result['column_discovery_error'] = discovery_error
                    return result
            else:
                if _discovery_filters_match_observed_steps(result, discovery_filters):
                    discovery_ok, discovery_error = _run_multistep_column_discovery_on_current_wizard(worker)
                    if not discovery_ok:
                        result['column_discovery_error'] = discovery_error
                        return result
                else:
                    navigation.close_report_page(worker)
                    frame = navigation.get_reports_frame(worker)
                    if not frame:
                        result['column_discovery_error'] = 'Reports iframe not found after schema discovery.'
                        return result
                    if not navigation.open_report(worker, frame, folder, name):
                        result['column_discovery_error'] = f'Could not reopen {folder}/{name} for column discovery.'
                        return result

                    worker.page.wait_for_timeout(worker.timeout_medium)
                    if not run_filter_wizard(worker, discovery_filters, require_run=True, discovery_mode=True):
                        result['column_discovery_error'] = 'Could not run the report for column discovery.'
                        return result
        else:
            worker.logger.info('Discovery: clicking Run to render the report for column discovery...')
            if not click_wizard_button(worker, 'Run'):
                worker.logger.warning('Discovery: could not click Run — column discovery skipped')
                result['column_discovery_error'] = 'Could not click Run for column discovery.'
                return result

        result['_columns_meta'] = _discover_columns_after_run(worker)
        worker.logger.info(
            f"Discovery: columns_meta={{"
            f"columns:{len(result['_columns_meta'].get('available', []))}, "
            f"datetime_field:{result['_columns_meta'].get('datetime_field')!r}}}"
        )
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
