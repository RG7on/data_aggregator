"""
CUIC Data Scraper
=================
Methods for scraping data from CUIC reports.
Supports multiple fallback strategies:
1. ag-grid JavaScript API (best - gets ALL rows)
2. ag-grid DOM scraping (fallback - only visible rows)
3. Plain HTML tables (last resort)
"""

import re
from typing import Dict, Any, List
from datetime import datetime
from . import javascript


_DURATION_RE = re.compile(r'^-?\d{1,3}:\d{2}:\d{2}$')
_NUMERIC_RE = re.compile(r'^-?\d+(?:\.\d+)?$')
_DIMENSION_HEADERS = frozenset({
    'agent', 'full name', 'agent skill target id', 'skill group id',
    'skill group name', 'media', 'media id', 'interval', 'date',
    'time zone', 'call type', 'queue', 'team', 'user', 'device',
    'extension', 'precision queue', 'precision queue name',
})
_SKIP_DATE_WORDS = frozenset({'created', 'updated', 'modified'})
_DATETIME_FORMATS = (
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d',
    '%m/%d/%Y %I:%M:%S %p',
    '%m/%d/%y %I:%M:%S %p',
    '%m/%d/%Y',
    '%m/%d/%y',
    '%b %d, %Y %I:%M:%S %p',
    '%B %d, %Y %I:%M:%S %p',
)


def _normalize_name(value: Any) -> str:
    return str(value or '').strip().lower()


def _field_value(row: Dict[str, Any], field: str, header: str) -> Any:
    if field:
        return row.get(field, row.get(header, ''))
    return row.get(header, '')


def _score_datetime_header(header: str) -> int:
    hn = _normalize_name(header)
    if not hn:
        return -1
    if hn == 'interval':
        return 120
    if hn in ('datetime', 'date time', 'date/time'):
        return 110
    if hn == 'database datetime':
        return 100
    if 'interval' in hn:
        return 90
    if 'date' in hn and not any(token in hn for token in _SKIP_DATE_WORDS):
        return 80
    return -1


def _format_dimension_value(header: str, value: Any) -> str:
    text = str(value).strip() if value is not None else ''
    if not text:
        return ''
    if _score_datetime_header(header) >= 0:
        parsed = _parse_dt(text)
        if parsed:
            return parsed
    return text


def _parse_dt(val) -> str:
    """Parse a DateTime value (Unix ms timestamp) into 'YYYY-MM-DD HH:MM:SS'.
    Returns '' if val is empty or not a recognisable timestamp."""
    s = str(val).strip() if val is not None else ''
    if not s:
        return ''
    if s and len(s) == 13 and s.isdigit():
        try:
            dt = datetime.fromtimestamp(int(s) / 1000)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OSError, OverflowError):
            pass
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S') if dt.time() != datetime.min.time() else dt.strftime('%Y-%m-%d')
    except ValueError:
        pass
    for fmt in _DATETIME_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            has_time = '%H' in fmt or '%I' in fmt
            return dt.strftime('%Y-%m-%d %H:%M:%S') if has_time else dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
    return ''


def _classify_value_kind(value: Any) -> str:
    text = str(value).strip() if value is not None else ''
    if not text:
        return 'empty'
    if _parse_dt(text):
        return 'datetime'
    if text.endswith('%') and _NUMERIC_RE.match(text[:-1].strip()):
        return 'percent'
    if _DURATION_RE.match(text):
        return 'duration'
    normalized = text.replace(',', '')
    if _NUMERIC_RE.match(normalized):
        return 'numeric'
    return 'text'


def _detect_datetime_field(fields: List[str], hdrs: List[str], report_config: dict, cols_meta: dict) -> str:
    explicit = str((report_config or {}).get('datetime_column') or '').strip()
    if explicit:
        explicit_norm = _normalize_name(explicit)
        for field, hdr in zip(fields, hdrs):
            if explicit_norm in {_normalize_name(field), _normalize_name(hdr)}:
                return field

    best_field = ''
    best_score = -1
    for field, hdr in zip(fields, hdrs):
        score = _score_datetime_header(hdr)
        if score > best_score:
            best_field = field
            best_score = score

    saved_hint = str((cols_meta or {}).get('datetime_field') or '').strip()
    if saved_hint:
        saved_norm = _normalize_name(saved_hint)
        for field, hdr in zip(fields, hdrs):
            if saved_norm in {_normalize_name(field), _normalize_name(hdr)}:
                saved_score = _score_datetime_header(hdr)
                if saved_score >= best_score:
                    return field
                break
    return best_field


def _collect_column_stats(rows: List[Dict[str, Any]], fields: List[str], hdrs: List[str]) -> List[Dict[str, Any]]:
    stats = []
    for field, hdr in zip(fields, hdrs):
        kind_counts: Dict[str, int] = {}
        distinct_values = set()
        non_empty = 0
        for row in rows:
            if row.get('__isGroupNode') or row.get('__isPinnedBottom'):
                continue
            text = str(_field_value(row, field, hdr) or '').strip()
            if not text:
                continue
            non_empty += 1
            distinct_values.add(text)
            kind = _classify_value_kind(text)
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        stats.append({
            'non_empty': non_empty,
            'distinct': len(distinct_values),
            'kind_counts': kind_counts,
        })
    return stats


def _detect_report_pattern(rows: List[Dict[str, Any]], group_fields: List[str], report_config: dict) -> str:
    explicit = _normalize_name((report_config or {}).get('structure_mode'))
    if explicit in {'grouped', 'wide'}:
        return explicit
    if group_fields:
        return 'grouped'
    if any(row.get('__groupPath') or row.get('__isGroupNode') for row in rows):
        return 'grouped'
    return 'wide'


def _matches_column_ref(field: str, header: str, refs: set[str]) -> bool:
    return _normalize_name(field) in refs or _normalize_name(header) in refs


def _infer_column_roles(
    fields: List[str],
    hdrs: List[str],
    rows: List[Dict[str, Any]],
    group_fields: List[str],
    dt_field: str,
    report_config: dict,
) -> List[str]:
    cfg = report_config or {}
    pattern = _detect_report_pattern(rows, group_fields, cfg)
    explicit_dims = {_normalize_name(value) for value in (cfg.get('dimension_columns') or []) if str(value).strip()}
    explicit_ignored = {_normalize_name(value) for value in (cfg.get('ignored_columns') or []) if str(value).strip()}
    group_refs = {_normalize_name(value) for value in group_fields if str(value).strip()}
    dt_norm = _normalize_name(dt_field)
    stats = _collect_column_stats(rows, fields, hdrs)

    roles: List[str] = []
    for idx, (field, hdr) in enumerate(zip(fields, hdrs)):
        hdr_norm = _normalize_name(hdr)
        field_norm = _normalize_name(field)
        stat = stats[idx]
        kind_counts = stat['kind_counts']
        non_empty = stat['non_empty']
        numeric_like = sum(kind_counts.get(kind, 0) for kind in ('numeric', 'percent', 'duration'))
        text_like = kind_counts.get('text', 0)
        datetime_like = kind_counts.get('datetime', 0)

        if _matches_column_ref(field, hdr, explicit_ignored):
            roles.append('ignored')
            continue
        if dt_norm and field_norm == dt_norm:
            roles.append('datetime')
            continue
        if _matches_column_ref(field, hdr, explicit_dims):
            roles.append('dimension')
            continue
        if pattern == 'grouped':
            if field_norm in group_refs or (idx == 0 and not field_norm):
                roles.append('dimension')
            else:
                roles.append('metric')
            continue

        header_marks_dimension = hdr_norm in _DIMENSION_HEADERS or hdr_norm.endswith(' id') or hdr_norm.endswith(' name')
        if header_marks_dimension:
            roles.append('dimension')
        elif datetime_like and non_empty and datetime_like == non_empty:
            roles.append('dimension')
        elif text_like and non_empty and text_like == non_empty and stat['distinct'] >= 2:
            roles.append('dimension')
        elif non_empty and numeric_like >= max(1, non_empty - text_like):
            roles.append('metric')
        else:
            roles.append('metric')

    if pattern == 'wide' and 'dimension' not in roles and roles:
        fallback_index = next((idx for idx, stat in enumerate(stats) if stat['kind_counts'].get('text', 0)), 0)
        if roles[fallback_index] == 'metric':
            roles[fallback_index] = 'dimension'
    return roles


def _derive_group_labels(row: Dict[str, Any], fields: List[str], last_category: str) -> tuple[str, str, str]:
    """Derive category/sub_category from ag-grid group metadata when available."""
    if row.get('__isPinnedBottom'):
        return '', '', last_category

    path = row.get('__groupPath') or []
    if isinstance(path, list):
        keys = [
            str(segment.get('key', '')).strip()
            for segment in path
            if isinstance(segment, dict) and str(segment.get('key', '')).strip()
        ]
        if keys:
            category = keys[0]
            sub_category = ' | '.join(keys[1:]) if len(keys) > 1 else ''
            return category, sub_category, category

    raw_category = str(row.get(fields[0], '') if fields and fields[0] else '').strip()
    if raw_category:
        last_category = raw_category
    return last_category, '', last_category


def _derive_wide_labels(row: Dict[str, Any], fields: List[str], hdrs: List[str], dimension_indices: List[int]) -> tuple[str, str]:
    pairs = []
    for idx in dimension_indices:
        value = _format_dimension_value(hdrs[idx], _field_value(row, fields[idx], hdrs[idx]))
        if not value:
            continue
        pairs.append((hdrs[idx], value))
    if not pairs:
        return '', ''
    category = pairs[0][1]
    sub_category = ' | '.join(f"{name}={value}" for name, value in pairs[1:])
    return category, sub_category


def _normalize_rows(
    worker,
    rows: List[Dict[str, Any]],
    hdrs: List[str],
    fields: List[str],
    report_label: str,
    report_config: dict,
    group_fields: List[str] | None = None,
) -> List[Dict[str, Any]]:
    cfg = report_config or {}
    report_id = str(cfg.get('report_id', '') or '').strip()
    definition_hash = str(cfg.get('definition_hash', '') or '').strip()
    row_mode = cfg.get('row_mode', 'consolidated_only')
    cols_meta = cfg.get('_columns_meta') or {}
    dt_field = _detect_datetime_field(fields, hdrs, cfg, cols_meta)
    pattern = _detect_report_pattern(rows, group_fields or [], cfg)
    roles = _infer_column_roles(fields, hdrs, rows, group_fields or [], dt_field, cfg)

    selected_cols = cfg.get('columns')
    selected_refs = None
    if selected_cols is not None:
        selected_refs = {_normalize_name(value) for value in selected_cols if str(value).strip()}

    dimension_indices = [idx for idx, role in enumerate(roles) if role == 'dimension']
    metric_indices = []
    for idx, role in enumerate(roles):
        if role != 'metric':
            continue
        if selected_refs is not None and _normalize_name(hdrs[idx]) not in selected_refs and _normalize_name(fields[idx]) not in selected_refs:
            continue
        metric_indices.append(idx)

    worker.logger.info(
        "    Normalizer: pattern=%s, datetime=%r, dimensions=%s, metrics=%d",
        pattern,
        dt_field,
        [hdrs[idx] for idx in dimension_indices],
        len(metric_indices),
    )

    data = []
    last_cat = ''
    for row in rows:
        if pattern == 'grouped':
            category, sub_category, last_cat = _derive_group_labels(row, fields, last_cat)
        else:
            category, sub_category = _derive_wide_labels(row, fields, hdrs, dimension_indices)
            if not category and row_mode == 'consolidated_only':
                category = ''
                sub_category = ''
            elif not category:
                continue

        data_datetime = _parse_dt(_field_value(row, dt_field, dt_field) if dt_field else '')

        for idx in metric_indices:
            value = _field_value(row, fields[idx], hdrs[idx])
            text = str(value).strip() if value is not None else ''
            if text == '':
                continue
            data.append({
                'metric_title': f"CUIC_{hdrs[idx]}",
                'report_id': report_id,
                'definition_hash': definition_hash,
                'report_name': report_label,
                'category': category,
                'sub_category': sub_category,
                'data_datetime': data_datetime,
                'value': text,
            })
    return data


def scrape_data(worker, report_label: str = '', report_config: dict = None) -> List[Dict[str, Any]]:
    """Main scraper entry point. Tries all methods in order."""
    try:
        # Wait for report content to render — try ag-grid first, then fixed timeout
        worker.logger.info(f"  Waiting for report data to render...")
        all_pages = worker.context.pages
        target = all_pages[-1] if len(all_pages) > 1 else worker.page
        try:
            target.wait_for_selector(
                '.ag-root, .ag-body-viewport, [class*="ag-theme"], table',
                timeout=worker.timeout_long)
        except Exception:
            worker.logger.info(f"  No grid/table detected within {worker.timeout_long}ms, continuing anyway")
        worker.logger.info(f"  Scraper: {len(all_pages)} page(s), "
                         f"targeting {'last page' if len(all_pages) > 1 else 'main page'}")
        worker.logger.info(f"  Target has {len(target.frames)} frame(s)")

        for fi, frame in enumerate(target.frames):
            url_short = frame.url[:80] if frame.url else '(empty)'
            has_ag = False
            try:
                has_ag = bool(frame.query_selector('.ag-root, .ag-body-viewport, [class*="ag-theme"]'))
            except Exception:
                pass

            if not has_ag:
                continue

            worker.logger.info(f"  Frame {fi}: ag-grid detected ({url_short})")

            data = _scrape_ag_grid_api(worker, frame, report_label, report_config)
            if data:
                worker.logger.info(f"Scraped {len(data)} records via ag-grid JS API")
                worker.screenshot("04_done")
                return data

            data = _scrape_ag_grid_dom(worker, frame, report_label, report_config)
            if data:
                worker.logger.info(f"Scraped {len(data)} records via ag-grid DOM fallback")
                worker.screenshot("04_done")
                return data

            data = _scrape_html_tables(worker, frame, report_label, report_config)
            if data:
                worker.logger.info(f"Scraped {len(data)} records from HTML tables")
                worker.screenshot("04_done")
                return data

            worker.logger.info(f"  Frame {fi}: ag-grid found but no data rows extracted")

        worker.logger.warning("No report data found in any frame")
        worker.screenshot("no_data", is_step=False)
        return []
    except Exception as e:
        worker.logger.error(f"Scrape failed: {e}")
        import traceback
        worker.logger.error(f"  {traceback.format_exc()}")
        worker.screenshot("scrape_error", is_step=False)
        return []


def _scrape_ag_grid_api(worker, frame, report_label: str = '', report_config: dict = None) -> List[Dict[str, Any]]:
    """Extract data via ag-grid's internal JS API.
    Returns ALL rows regardless of virtual scroll viewport."""
    try:
        if not frame.query_selector('.ag-root, .ag-body-viewport, [class*="ag-theme"]'):
            return []

        result = frame.evaluate(javascript.AG_GRID_JS)

        if not isinstance(result, dict):
            worker.logger.info("    ag-grid JS API: unexpected return type")
            return []
        if 'error' in result:
            worker.logger.info(f"    ag-grid JS API: {result['error']}")
            return []

        columns = result['columns']
        rows    = result['rows']
        worker.logger.info(f"    ag-grid JS API: {len(columns)} columns, {result['rowCount']} rows")

        # Build header names (prefer headerName, fall back to field)
        hdrs = [c.get('headerName') or c.get('field', f'col_{i}')
                for i, c in enumerate(columns)]
        fields = [c.get('field', '') for c in columns]

        # ── Ensure fields[0] is the real category field ───────────────
        # The ag-grid auto-group display column has field="" so fields[0]
        # would be empty.  When the JS returned groupFields (detected by
        # walking node.parent), use the first one as the category field so
        # row.get(fields[0]) actually returns the Call Type name.
        js_group_fields = result.get('groupFields', [])
        if (not fields[0]) and js_group_fields:
            fields[0] = js_group_fields[0]
            # Also update columns[0] so column-filter logic is consistent
            if columns:
                columns[0] = dict(columns[0], field=fields[0])
            worker.logger.info(f"    Category field overridden from groupFields: {fields[0]!r}")
        elif not fields[0]:
            worker.logger.warning(
                "    Category field is empty and no groupFields detected – "
                "category column will be blank"
            )

        worker.logger.info(f"ag-grid columns: {hdrs}")

        # ── Row filtering ─────────────────────────────────────────────
        cfg          = report_config or {}
        row_mode     = cfg.get('row_mode', 'consolidated_only')
        cols_meta    = cfg.get('_columns_meta') or {}
        dt_field     = _detect_datetime_field(fields, hdrs, cfg, cols_meta)

        if row_mode == 'consolidated_only':
            before_count = len(rows)
            rows = [
                row for row in rows
                if row.get('__isGroupNode')
                or row.get('__isPinnedBottom')
                or (dt_field and not row.get(dt_field))
            ]
            worker.logger.info(
                f"    Row filter (consolidated_only, dt_field={dt_field!r}): "
                f"{before_count} → {len(rows)} rows "
                f"(group={sum(1 for r in rows if r.get('__isGroupNode'))}, "
                f"pinned={sum(1 for r in rows if r.get('__isPinnedBottom'))}, "
                f"blank_dt={sum(1 for r in rows if dt_field and not r.get(dt_field))})"
            )
            if not rows:
                worker.logger.warning(
                    "    Row filter: consolidated_only found no grouped/pinned/blank-datetime rows — "
                    "returning all rows"
                )
                rows = result['rows']

        return _normalize_rows(worker, rows, hdrs, fields, report_label, cfg, group_fields=result.get('groupFields', []))
    except Exception as e:
        worker.logger.debug(f"ag-grid JS API failed: {e}")
        return []


def _scrape_ag_grid_dom(worker, frame, report_label: str = '', report_config: dict = None) -> List[Dict[str, Any]]:
    """DOM-based scraping. Only gets rows rendered in viewport."""
    try:
        if not frame.query_selector('.ag-root, .ag-body-viewport'):
            return []
        hdrs = [h.inner_text().strip() for h in frame.query_selector_all(
            '.ag-header-cell .ag-header-cell-text, '
            '.ag-header-cell-label .ag-header-cell-text'
        ) if h.inner_text().strip()]
        if len(hdrs) < 2:
            return []
        worker.logger.info(f"ag-grid DOM columns: {hdrs}")

        cfg = report_config or {}
        row_mode = cfg.get('row_mode', 'consolidated_only')
        if row_mode == 'consolidated_only':
            worker.logger.warning(
                "    Row filter: DOM fallback scraper cannot reliably detect "
                "consolidated rows — returning all visible rows"
            )

        rows = []
        for row in frame.query_selector_all('.ag-row'):
            vals = [c.inner_text().strip() for c in row.query_selector_all('.ag-cell')]
            if not vals or all(v == '' for v in vals):
                continue
            while len(vals) < len(hdrs):
                vals.append('')
            rows.append({hdrs[idx]: vals[idx] for idx in range(len(hdrs))})
        return _normalize_rows(worker, rows, hdrs, hdrs[:], report_label, cfg)
    except Exception:
        return []


def _scrape_html_tables(worker, frame, report_label: str = '', report_config: dict = None) -> List[Dict[str, Any]]:
    """Fallback: scrape plain HTML tables."""
    try:
        cfg = report_config or {}
        data = []
        for table in frame.query_selector_all('table'):
            rows = table.query_selector_all('tr')
            if len(rows) < 2:
                continue
            hdrs = [c.inner_text().strip() for c in rows[0].query_selector_all('th, td')]
            if len(hdrs) < 2:
                continue
            table_rows = []
            for row in rows[1:]:
                vals = [c.inner_text().strip() for c in row.query_selector_all('td')]
                if not vals or len(vals) < 2:
                    continue
                while len(vals) < len(hdrs):
                    vals.append('')
                table_rows.append({hdrs[idx]: vals[idx] for idx in range(len(hdrs))})
            data.extend(_normalize_rows(worker, table_rows, hdrs, hdrs[:], report_label, cfg))
        return data
    except Exception:
        return []
