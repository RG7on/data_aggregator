"""
CUIC Report Worker
==================
Scrapes Cisco Unified Intelligence Center (CUIC) ag-grid report data.
Supports multiple reports configured in settings.json.

Flow:
  1. Login (2-stage: username → password + LDAP)
  2. For each enabled report:
     a. Navigate to Reports tab → enter reports iframe
     b. Click folder → click report (single-click, ng-grid)
     c. Filter wizard: Next → Next → Run
     d. Scrape ag-grid data → long-format dicts
     e. Close report tab → return to reports list
"""

import os, sys, re, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_worker import BaseWorker
from core.config import get_worker_settings, get_worker_credentials
from core.database import log_scrape
from typing import Dict, Any, List


class Worker(BaseWorker):
    SOURCE_NAME = "cuic"
    DESCRIPTION = "Cisco Unified Intelligence Center Scraper"

    # ── Selectors ─────────────────────────────────────────────────────────
    # Login
    USERNAME_XPATH       = 'xpath=/html/body/form/div/div/div/div/div[1]/div[3]/input[1]'
    NEXT_BTN_XPATH       = 'xpath=/html/body/form/div/div/div/div/div[2]/button[1]'
    PASSWORD_XPATH       = 'xpath=/html/body/form/div/div/div/div/div[1]/div[2]/input[2]'
    DOMAIN_SELECT_XPATH  = 'xpath=/html/body/form/div/div/div/div/div[1]/div[3]/select'
    SIGN_IN_BTN_XPATH    = 'xpath=/html/body/form/div/div/div/div/div[2]/button[1]'
    # Main page
    REPORTS_TAB_CSS      = 'a[href="#/reports"]'
    REPORTS_IFRAME_NAME  = 'remote_iframe_3'
    # ng-grid (reports list)
    GRID_CONTAINER       = '.ngGrid'
    GRID_VIEWPORT        = '.ngViewport'
    GRID_ROW             = '.ngRow'
    NAME_CELL            = '.name_cell_container.colt0'
    NAME_TEXT            = '.nameCell span.ellipsis, .nameCell span.ellipses'
    FOLDER_ICON          = '.icon.icon-folder'
    REPORT_ICON          = '.icon.icon-report'

    # ══════════════════════════════════════════════════════════════════════
    #  CONFIG
    # ══════════════════════════════════════════════════════════════════════
    def _load_config(self):
        cfg  = get_worker_settings('cuic')
        cred = get_worker_credentials('cuic')

        self.url         = cfg.get('url', 'https://148.151.32.77:8444/cuicui/Main.jsp')
        self.reports     = cfg.get('reports', [{
            'label': 'call_type_hist',
            'folder': 'Test',
            'name': 'Z Call Type Historical All Fields',
            'enabled': True,
            'filters': {}
        }])
        self.username    = cred.get('username', '')
        self.password    = cred.get('password', '')
        self.timeout_nav    = cfg.get('timeout_nav_ms',    30000)
        self.timeout_short  = cfg.get('timeout_short_ms',  1500)
        self.timeout_medium = cfg.get('timeout_medium_ms', 2500)
        self.timeout_long   = cfg.get('timeout_long_ms',   8000)

    # ══════════════════════════════════════════════════════════════════════
    #  ENTRY
    # ══════════════════════════════════════════════════════════════════════
    def run(self) -> List[Dict[str, Any]]:
        self._load_config()
        if not self.username or not self.password:
            self.logger.error("CUIC credentials not set in config/credentials.json")
            return []

        enabled = [r for r in self.reports if r.get('enabled', True)]
        if not enabled:
            self.logger.info("No enabled CUIC reports configured")
            return []

        self.logger.info(f"Starting CUIC scraper → {self.url} ({len(enabled)} report(s))")
        try:
            self.setup_browser(ignore_https_errors=True)
            return self.scrape()
        except Exception as e:
            self.logger.error(f"CUIC worker error: {e}")
            self.screenshot("error", is_step=False)
            return []
        finally:
            self.teardown_browser()

    def scrape(self) -> List[Dict[str, Any]]:
        if not self._login():
            return []

        all_data = []
        enabled = [r for r in self.reports if r.get('enabled', True)]

        for i, report in enumerate(enabled):
            label  = report.get('label', f'report_{i}')
            folder = report.get('folder', '')
            name   = report.get('name', '')

            self.logger.info(f"━━━ Report {i+1}/{len(enabled)}: {label} ({folder}/{name}) ━━━")
            t0 = time.time()

            try:
                # Between reports: close extra tabs, navigate back to reports root
                if i > 0:
                    self._close_report_page()
                    self._navigate_to_reports_root()

                frame = self._get_reports_frame()
                if not frame:
                    log_scrape('cuic', label, 'error', 0, time.time() - t0,
                               'Reports iframe not found')
                    continue

                if not self._open_report(frame, folder, name):
                    log_scrape('cuic', label, 'error', 0, time.time() - t0,
                               f'Could not open {folder}/{name}')
                    continue

                if not self._run_filter_wizard():
                    log_scrape('cuic', label, 'error', 0, time.time() - t0,
                               'Filter wizard failed')
                    continue

                data = self._scrape_data(label)
                elapsed = time.time() - t0

                if data:
                    all_data.extend(data)
                    log_scrape('cuic', label, 'success', len(data), elapsed, '')
                    self.logger.info(
                        f"Report '{label}': {len(data)} records in {elapsed:.1f}s")
                else:
                    log_scrape('cuic', label, 'no_data', 0, elapsed, 'No data found')

            except Exception as e:
                log_scrape('cuic', label, 'error', 0, time.time() - t0, str(e))
                self.logger.error(f"Report '{label}' failed: {e}")

        # Final cleanup
        self._close_report_page()
        return all_data

    # ──────────────────────────────────────────────────────────────────────
    #  Navigation helpers for multi-report
    # ──────────────────────────────────────────────────────────────────────
    def _close_report_page(self):
        """Close any extra browser tabs opened by a report."""
        try:
            pages = self.context.pages
            while len(pages) > 1:
                pages[-1].close()
                pages = self.context.pages
        except Exception:
            pass

    def _navigate_to_reports_root(self):
        """Click the Reports tab to reset back to the reports list root."""
        try:
            self.page.click(self.REPORTS_TAB_CSS)
            self.page.wait_for_timeout(self.timeout_medium)
        except Exception as e:
            self.logger.warning(f"Navigate to reports root: {e}")

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 1 – LOGIN
    # ══════════════════════════════════════════════════════════════════════
    def _login(self) -> bool:
        try:
            self.page.goto(self.url, wait_until='domcontentloaded', timeout=self.timeout_nav)
            self.page.wait_for_timeout(self.timeout_short)

            # Stage 1: username → Next
            self.page.wait_for_selector(self.USERNAME_XPATH, timeout=self.timeout_nav)
            self.page.fill(self.USERNAME_XPATH, self.username)
            self.page.click(self.NEXT_BTN_XPATH)
            self.page.wait_for_load_state('domcontentloaded')
            self.page.wait_for_timeout(self.timeout_short)

            # Stage 2: password + LDAP → Sign In
            self.page.wait_for_selector(self.PASSWORD_XPATH, timeout=self.timeout_nav)
            self.page.fill(self.PASSWORD_XPATH, self.password)
            self.page.select_option(self.DOMAIN_SELECT_XPATH, value="LDAP")
            self.page.click(self.SIGN_IN_BTN_XPATH)

            self.page.wait_for_selector(self.REPORTS_TAB_CSS, timeout=self.timeout_nav)
            self.logger.info("Login OK")
            self.screenshot("01_login_ok")
            return True
        except Exception as e:
            self.logger.error(f"Login failed: {e}")
            self.screenshot("login_error", is_step=False)
            return False

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 2 – GET REPORTS IFRAME
    # ══════════════════════════════════════════════════════════════════════
    def _get_reports_frame(self):
        try:
            self.page.click(self.REPORTS_TAB_CSS)
            self.page.wait_for_timeout(self.timeout_medium)

            frame = self.page.frame(name=self.REPORTS_IFRAME_NAME)
            if not frame:
                # fallback: find frame with ng-grid
                for f in self.page.frames:
                    try:
                        if f.query_selector(self.GRID_CONTAINER):
                            frame = f
                            break
                    except Exception:
                        pass
            if not frame:
                self.logger.error("Reports iframe not found")
                self.screenshot("iframe_missing", is_step=False)
                return None

            frame.wait_for_selector(self.GRID_CONTAINER, timeout=self.timeout_nav)
            self.logger.info("Reports iframe ready")
            return frame
        except Exception as e:
            self.logger.error(f"Reports iframe error: {e}")
            self.screenshot("iframe_error", is_step=False)
            return None

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 3 – NAVIGATE FOLDER → CLICK REPORT
    # ══════════════════════════════════════════════════════════════════════
    def _open_report(self, frame, folder_path: str, report_name: str) -> bool:
        """Navigate through a folder path (e.g. 'Stock/CCE/CCE_AF_Historical')
        then click the report. Supports any nesting depth."""
        try:
            # Split folder path into segments — supports / or \ delimiters
            folders = [f.strip() for f in folder_path.replace('\\', '/').split('/') if f.strip()]

            for depth, folder in enumerate(folders):
                if not self._click_grid_item(frame, folder, is_folder=True):
                    # Try scrolling to find it
                    if not self._scroll_and_click_folder(frame, folder):
                        self.logger.error(f"Folder '{folder}' not found (depth {depth})")
                        self._dump_grid(frame)
                        self.screenshot("folder_not_found", is_step=False)
                        return False
                self.logger.info(f"Opened folder '{folder}' (depth {depth})")

                self.page.wait_for_timeout(self.timeout_medium)

                # Re-acquire frame if it detached
                frame = self._reacquire_frame(frame)
                if not frame:
                    return False

                # Wait for grid to refresh with new folder contents
                try:
                    frame.wait_for_selector(self.GRID_CONTAINER, timeout=self.timeout_nav)
                except Exception:
                    self.page.wait_for_timeout(self.timeout_short)

            # Click the report itself
            if not self._click_grid_item(frame, report_name, is_folder=False):
                if not self._scroll_and_click(frame, report_name):
                    self.logger.error(f"Report '{report_name}' not found")
                    self._dump_grid(frame)
                    self.screenshot("report_not_found", is_step=False)
                    return False
            self.logger.info(f"Clicked report '{report_name}'")
            self.page.wait_for_timeout(self.timeout_medium)
            self.screenshot("02_report_clicked")
            return True
        except Exception as e:
            self.logger.error(f"Open report failed: {e}")
            self.screenshot("open_report_error", is_step=False)
            return False

    def _reacquire_frame(self, frame):
        """Re-acquire the reports iframe if it detached after a click."""
        try:
            frame.query_selector('body')
            return frame
        except Exception:
            frame = self.page.frame(name=self.REPORTS_IFRAME_NAME)
            if not frame:
                self.logger.error("Frame detached and could not be re-acquired")
            return frame

    def _scroll_and_click_folder(self, frame, name: str, max_scrolls: int = 20) -> bool:
        """Scroll through the ng-grid viewport to find and click a folder."""
        try:
            vp = frame.query_selector(self.GRID_VIEWPORT)
            if not vp:
                return False
            for _ in range(max_scrolls):
                frame.evaluate('''s => {
                    const vp = document.querySelector(s);
                    if (vp) vp.scrollTop += vp.clientHeight;
                }''', self.GRID_VIEWPORT)
                self.page.wait_for_timeout(400)
                if self._click_grid_item(frame, name, is_folder=True):
                    return True
            return False
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────────────
    #  Grid helpers
    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _norm(text: str) -> str:
        return re.sub(r'\s+', ' ', text.strip())

    def _click_grid_item(self, frame, name: str, is_folder: bool = False) -> bool:
        """Single-click an item in the ng-grid. Returns True if clicked."""
        target = self._norm(name)

        # Fast path: title attribute (most reliable, one query)
        try:
            el = frame.query_selector(f'.nameCell span[title="{name}"]')
            if el:
                container = el.evaluate_handle(
                    'el => el.closest(".name_cell_container") || el'
                ).as_element()
                container.click()
                return True
        except Exception:
            pass

        # DOM scan (handles whitespace / class variations)
        try:
            for row in frame.query_selector_all(self.GRID_ROW):
                name_el = row.query_selector(self.NAME_TEXT)
                if not name_el:
                    continue
                txt = self._norm(name_el.inner_text())
                title = self._norm(name_el.get_attribute('title') or '')
                if txt != target and title != target:
                    continue
                # Verify icon type
                icon_sel = self.FOLDER_ICON if is_folder else self.REPORT_ICON
                if not row.query_selector(icon_sel):
                    continue
                (row.query_selector(self.NAME_CELL) or name_el).click()
                return True
        except Exception:
            pass

        # JS fallback
        try:
            result = frame.evaluate('''(t) => {
                const norm = s => s.replace(/\\s+/g,' ').trim();
                const target = norm(t);
                for (const sp of document.querySelectorAll('.nameCell span')) {
                    if (norm(sp.textContent||'')===target || norm(sp.title||'')===target) {
                        const p = sp.closest('.name_cell_container') || sp.closest('.ngCellText');
                        if (p) { p.click(); return true; }
                    }
                }
                return false;
            }''', name)
            if result:
                return True
        except Exception:
            pass

        return False

    def _scroll_and_click(self, frame, name: str, max_scrolls: int = 20) -> bool:
        try:
            vp = frame.query_selector(self.GRID_VIEWPORT)
            if not vp:
                return False
            for _ in range(max_scrolls):
                frame.evaluate('''s => {
                    const vp = document.querySelector(s);
                    if (vp) vp.scrollTop += vp.clientHeight;
                }''', self.GRID_VIEWPORT)
                self.page.wait_for_timeout(400)
                if self._click_grid_item(frame, name, is_folder=False):
                    return True
            return False
        except Exception:
            return False

    def _dump_grid(self, frame):
        try:
            for i, row in enumerate(frame.query_selector_all(self.GRID_ROW)[:30]):
                el = row.query_selector(self.NAME_TEXT)
                txt = el.inner_text().strip() if el else '?'
                self.logger.info(f"  Grid[{i}]: {txt}")
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 4 – FILTER WIZARD (Next → Next → Run)
    # ══════════════════════════════════════════════════════════════════════
    def _run_filter_wizard(self) -> bool:
        try:
            self.page.wait_for_timeout(self.timeout_medium)

            frames = self.page.frames
            for btn_text in ["Next", "Next", "Next", "Run"]:
                clicked = False
                for f in frames:
                    try:
                        for sel in [
                            f'button:has-text("{btn_text}")',
                            f'input[type="button"][value="{btn_text}"]',
                        ]:
                            btn = f.query_selector(sel)
                            if btn and btn.is_visible():
                                btn.click()
                                self.page.wait_for_timeout(self.timeout_short)
                                clicked = True
                                break
                        if clicked:
                            break
                    except Exception:
                        pass
                if not clicked:
                    self.logger.debug(f"'{btn_text}' button not found (may be skipped)")

            self.page.wait_for_timeout(self.timeout_long)
            self.logger.info("Filter wizard done")
            self.screenshot("03_report_running")
            return True
        except Exception as e:
            self.logger.error(f"Filter wizard failed: {e}")
            self.screenshot("filter_error", is_step=False)
            return False

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 5 – SCRAPE ag-grid DATA
    # ══════════════════════════════════════════════════════════════════════

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

    def _scrape_data(self, report_label: str = '') -> List[Dict[str, Any]]:
        try:
            self.page.wait_for_timeout(self.timeout_long)

            all_pages = self.context.pages
            target = all_pages[-1] if len(all_pages) > 1 else self.page

            for frame in target.frames:
                # ── Primary: ag-grid JavaScript API (gets ALL rows) ──
                data = self._scrape_ag_grid_api(frame, report_label)
                if data:
                    self.logger.info(f"Scraped {len(data)} records via ag-grid JS API")
                    self.screenshot("04_done")
                    return data

                # ── Fallback 1: DOM scraping (visible rows only) ─────
                data = self._scrape_ag_grid_dom(frame, report_label)
                if data:
                    self.logger.info(f"Scraped {len(data)} records via ag-grid DOM fallback")
                    self.screenshot("04_done")
                    return data

                # ── Fallback 2: plain HTML tables ────────────────────
                data = self._scrape_html_tables(frame, report_label)
                if data:
                    self.logger.info(f"Scraped {len(data)} records from HTML tables")
                    self.screenshot("04_done")
                    return data

            self.logger.warning("No report data found in any frame")
            self.screenshot("no_data", is_step=False)
            return []
        except Exception as e:
            self.logger.error(f"Scrape failed: {e}")
            self.screenshot("scrape_error", is_step=False)
            return []

    # ──────────────────────────────────────────────────────────────────────
    #  PRIMARY: ag-grid JavaScript API
    # ──────────────────────────────────────────────────────────────────────
    def _scrape_ag_grid_api(self, frame, report_label: str = '') -> List[Dict[str, Any]]:
        """Extract data via ag-grid's internal JS API.
        Returns ALL rows regardless of virtual scroll viewport."""
        try:
            if not frame.query_selector('.ag-root, .ag-body-viewport, [class*="ag-theme"]'):
                return []

            result = frame.evaluate(self.AG_GRID_JS)

            if not isinstance(result, dict):
                self.logger.debug("ag-grid JS API: unexpected return type")
                return []
            if 'error' in result:
                self.logger.debug(f"ag-grid JS API: {result['error']}")
                return []

            columns = result['columns']
            rows    = result['rows']
            self.logger.info(f"ag-grid JS API: {len(columns)} columns, {result['rowCount']} rows")

            # Build header names (prefer headerName, fall back to field)
            hdrs = [c.get('headerName') or c.get('field', f'col_{i}')
                    for i, c in enumerate(columns)]
            fields = [c.get('field', '') for c in columns]

            self.logger.info(f"ag-grid columns: {hdrs}")

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
            self.logger.debug(f"ag-grid JS API failed: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────
    #  FALLBACK 1: ag-grid DOM scraping (original method)
    # ──────────────────────────────────────────────────────────────────────
    def _scrape_ag_grid_dom(self, frame, report_label: str = '') -> List[Dict[str, Any]]:
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
            self.logger.info(f"ag-grid DOM columns: {hdrs}")

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

    # ──────────────────────────────────────────────────────────────────────
    #  FALLBACK 2: plain HTML tables
    # ──────────────────────────────────────────────────────────────────────
    def _scrape_html_tables(self, frame, report_label: str = '') -> List[Dict[str, Any]]:
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
