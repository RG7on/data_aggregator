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
from . import javascript


def scrape_data(worker, report_label: str = '') -> List[Dict[str, Any]]:
    """Main scraper entry point. Tries all methods in order."""
    try:
        worker.page.wait_for_timeout(worker.timeout_long)

        all_pages = worker.context.pages
        target = all_pages[-1] if len(all_pages) > 1 else worker.page

        for frame in target.frames:
            # ── Primary: ag-grid JavaScript API (gets ALL rows) ──
            data = _scrape_ag_grid_api(worker, frame, report_label)
            if data:
                worker.logger.info(f"Scraped {len(data)} records via ag-grid JS API")
                worker.screenshot("04_done")
                return data

            # ── Fallback 1: DOM scraping (visible rows only) ─────
            data = _scrape_ag_grid_dom(worker, frame, report_label)
            if data:
                worker.logger.info(f"Scraped {len(data)} records via ag-grid DOM fallback")
                worker.screenshot("04_done")
                return data

            # ── Fallback 2: plain HTML tables ────────────────────
            data = _scrape_html_tables(worker, frame, report_label)
            if data:
                worker.logger.info(f"Scraped {len(data)} records from HTML tables")
                worker.screenshot("04_done")
                return data

        worker.logger.warning("No report data found in any frame")
        worker.screenshot("no_data", is_step=False)
        return []
    except Exception as e:
        worker.logger.error(f"Scrape failed: {e}")
        worker.screenshot("scrape_error", is_step=False)
        return []


def _scrape_ag_grid_api(worker, frame, report_label: str = '') -> List[Dict[str, Any]]:
    """Extract data via ag-grid's internal JS API.
    Returns ALL rows regardless of virtual scroll viewport."""
    try:
        if not frame.query_selector('.ag-root, .ag-body-viewport, [class*="ag-theme"]'):
            return []

        result = frame.evaluate(javascript.AG_GRID_JS)

        if not isinstance(result, dict):
            worker.logger.debug("ag-grid JS API: unexpected return type")
            return []
        if 'error' in result:
            worker.logger.debug(f"ag-grid JS API: {result['error']}")
            return []

        columns = result['columns']
        rows    = result['rows']
        worker.logger.info(f"ag-grid JS API: {len(columns)} columns, {result['rowCount']} rows")

        # Build header names (prefer headerName, fall back to field)
        hdrs = [c.get('headerName') or c.get('field', f'col_{i}')
                for i, c in enumerate(columns)]
        fields = [c.get('field', '') for c in columns]

        worker.logger.info(f"ag-grid columns: {hdrs}")

        # Convert to long-format dicts
        data = []
        for row in rows:
            # First column = category (Call Type, etc.)
            cat = str(row.get(fields[0], '') if fields[0] else '') if fields else ''

            for ci in range(1, len(columns)):
                field = fields[ci]
                val = row.get(field, '') if field else ''
                if val is None:
                    val = ''
                data.append({
                    'metric_title': f"CUIC_{hdrs[ci]}",
                    'category':     cat,
                    'sub_category': report_label,
                    'value':        str(val)
                })
        return data
    except Exception as e:
        worker.logger.debug(f"ag-grid JS API failed: {e}")
        return []


def _scrape_ag_grid_dom(worker, frame, report_label: str = '') -> List[Dict[str, Any]]:
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

        data = []
        for row in frame.query_selector_all('.ag-row'):
            vals = [c.inner_text().strip() for c in row.query_selector_all('.ag-cell')]
            if not vals or all(v == '' for v in vals):
                continue
            cat = vals[0]
            for ci in range(1, min(len(hdrs), len(vals))):
                data.append({
                    'metric_title': f"CUIC_{hdrs[ci]}",
                    'category': cat, 'sub_category': report_label, 'value': vals[ci]
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
            for row in rows[1:]:
                vals = [c.inner_text().strip() for c in row.query_selector_all('td')]
                if len(vals) < 2:
                    continue
                cat = vals[0]
                for ci in range(1, min(len(hdrs), len(vals))):
                    data.append({
                        'metric_title': f"CUIC_{hdrs[ci]}",
                        'category': cat, 'sub_category': report_label, 'value': vals[ci]
                    })
        return data
    except Exception:
        return []
