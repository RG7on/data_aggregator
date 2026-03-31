"""
CUIC Data Scraper
=================
Methods for scraping data from CUIC reports.
Supports multiple fallback strategies:
1. ag-grid JavaScript API (best - gets ALL rows)
2. ag-grid DOM scraping (fallback - only visible rows)
3. Plain HTML tables (last resort)
"""

from typing import Dict, Any, List
from datetime import datetime
from . import javascript


def _parse_dt(val) -> str:
    """Parse a DateTime value (Unix ms timestamp) into 'YYYY-MM-DD HH:MM:SS'.
    Returns '' if val is empty or not a recognisable timestamp."""
    s = str(val) if val is not None else ''
    if s and len(s) == 13 and s.isdigit():
        try:
            dt = datetime.fromtimestamp(int(s) / 1000)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OSError, OverflowError):
            pass
    return ''


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

            data = _scrape_html_tables(worker, frame, report_label)
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
        dt_field     = cols_meta.get('datetime_field', '')

        # Fallback: detect datetime field by column name heuristic
        if not dt_field and len(fields) > 1:
            skip_words = {'created', 'updated', 'modified', 'database'}
            for fi, (f_key, hdr) in enumerate(zip(fields, hdrs)):
                hn = hdr.strip().lower()
                if hn in ('datetime', 'date time', 'date/time'):
                    dt_field = f_key
                    break
            if not dt_field:
                for f_key, hdr in zip(fields, hdrs):
                    hn = hdr.strip().lower()
                    if 'date' in hn and not any(sw in hn for sw in skip_words):
                        dt_field = f_key
                        break
            if not dt_field:
                dt_field = fields[1] if len(fields) > 1 else ''

        if row_mode == 'consolidated_only' and dt_field:
            before_count = len(rows)
            rows = [r for r in rows if not r.get(dt_field)]
            worker.logger.info(
                f"    Row filter (consolidated_only, dt_field={dt_field!r}): "
                f"{before_count} → {len(rows)} rows"
            )
        elif row_mode == 'consolidated_only' and not dt_field:
            worker.logger.warning(
                "    Row filter: consolidated_only requested but "
                "datetime field not detected — returning all rows"
            )

        # ── Column filtering ─────────────────────────────────────────
        selected_cols = cfg.get('columns')  # None = all, list = selected headerNames
        if selected_cols is not None and len(selected_cols) > 0:
            selected_set = set(selected_cols)
            # Always keep index 0 (category/group key)
            keep_indices = [0] + [
                ci for ci in range(1, len(columns))
                if hdrs[ci] in selected_set
            ]
            columns = [columns[ci] for ci in keep_indices]
            hdrs    = [hdrs[ci]    for ci in keep_indices]
            fields  = [fields[ci]  for ci in keep_indices]
            worker.logger.info(
                f"    Column filter: {len(keep_indices)} / {len(result['columns'])} columns kept"
            )

        # Convert to long-format dicts
        data = []
        last_cat = ''   # carry-forward call type via sequential group tracking
        for row in rows:
            # Pinned-bottom rows are the global grand total (across ALL call types).
            # They must NOT inherit a call type from carry-forward — leave category=''.
            is_pinned = row.get('__isPinnedBottom', False)

            raw_cat = str(row.get(fields[0], '') if fields[0] else '') if fields else ''
            if not is_pinned:
                if raw_cat:
                    last_cat = raw_cat
                cat = last_cat
            else:
                cat = ''  # global grand total — no specific call type

            # Extract the datetime from the report's DateTime field.
            dt_raw = row.get(dt_field, '') if dt_field else ''
            data_datetime = _parse_dt(dt_raw)

            for ci in range(1, len(columns)):
                field = fields[ci]
                if dt_field and field == dt_field:
                    continue  # DateTime stored as data_datetime, not as a metric
                val = row.get(field, '') if field else ''
                if val is None:
                    val = ''
                data.append({
                    'metric_title':  f"CUIC_{hdrs[ci]}",
                    'report_name':   report_label,
                    'category':      cat,
                    'sub_category':  '',
                    'data_datetime': data_datetime,
                    'value':         str(val)
                })
        return data
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

        # Build column keep-set from selected_cols setting
        selected_cols = cfg.get('columns')
        if selected_cols is not None and len(selected_cols) > 0:
            selected_set = set(selected_cols)
            keep_indices = [0] + [ci for ci in range(1, len(hdrs)) if hdrs[ci] in selected_set]
        else:
            keep_indices = list(range(len(hdrs)))

        data = []
        for row in frame.query_selector_all('.ag-row'):
            vals = [c.inner_text().strip() for c in row.query_selector_all('.ag-cell')]
            if not vals or all(v == '' for v in vals):
                continue
            # Pad vals to match hdrs length
            while len(vals) < len(hdrs):
                vals.append('')
            cat = vals[0]
            for ci in keep_indices[1:]:
                if ci < len(hdrs) and ci < len(vals):
                    data.append({
                        'metric_title': f"CUIC_{hdrs[ci]}",
                        'report_name': report_label,
                        'category': cat, 'sub_category': '', 'value': vals[ci]
                    })
        return data
    except Exception:
        return []


def _scrape_html_tables(worker, frame, report_label: str = '') -> List[Dict[str, Any]]:
    """Fallback: scrape plain HTML tables."""
    try:
        data = []
        for table in frame.query_selector_all('table'):
            rows = table.query_selector_all('tr')
            if len(rows) < 2:
                continue
            hdrs = [c.inner_text().strip() for c in rows[0].query_selector_all('th, td')]
            if len(hdrs) < 2:
                continue
            prefix = f"CUIC_{report_label}_" if report_label else "CUIC_"
            for row in rows[1:]:
                vals = [c.inner_text().strip() for c in row.query_selector_all('td')]
                if len(vals) < 2:
                    continue
                cat = vals[0]
                for ci in range(1, min(len(hdrs), len(vals))):
                    data.append({
                        'metric_title': f"CUIC_{hdrs[ci]}",
                        'report_name': report_label,
                        'category': cat, 'sub_category': '', 'value': vals[ci]
                    })
        return data
    except Exception:
        return []
