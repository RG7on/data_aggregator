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
            self._logout()
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

                filters = report.get('filters', {})
                if not self._run_filter_wizard(filters):
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
    #  Logout – always called before closing the browser
    # ──────────────────────────────────────────────────────────────────────
    def _logout(self):
        """Sign out of CUIC so the session is released.
        This must run even after scraping errors to prevent
        'Session Limit Reached' on subsequent runs."""
        try:
            if not self.page or self.page.is_closed():
                self.logger.warning("Page already closed – skipping logout")
                return

            # Make sure we are on the main page (close extra tabs first)
            self._close_report_page()

            # Click the user dropdown
            user_btn = self.page.locator('#user-info-btn')
            user_btn.wait_for(state='visible', timeout=self.timeout_medium)
            user_btn.click()
            self.page.wait_for_timeout(800)

            # Click Sign Out
            signout = self.page.locator('#signout-btn1')
            signout.wait_for(state='visible', timeout=self.timeout_medium)
            signout.click()

            # Wait briefly for the sign-out to process
            self.page.wait_for_timeout(2000)
            self.logger.info("Logged out of CUIC successfully")
            self.screenshot("logout_ok")
        except Exception as e:
            self.logger.warning(f"Logout failed (session may persist): {e}")
            self.screenshot("logout_error", is_step=False)

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
            # Ensure focus is on the main page
            self.page.bring_to_front()
        except Exception:
            pass

    def _navigate_to_reports_root(self):
        """Reset back to the reports list. If the ngGrid is still hidden
        after clicking the Reports tab, reload the page to restore UI state."""
        try:
            # Attempt 1: click the Reports tab
            self.page.click(self.REPORTS_TAB_CSS)
            self.page.wait_for_timeout(self.timeout_medium)

            # Check if the ngGrid is visible in the reports iframe
            frame = self.page.frame(name=self.REPORTS_IFRAME_NAME)
            if frame:
                try:
                    grid = frame.query_selector(self.GRID_CONTAINER)
                    if grid and grid.is_visible():
                        self.logger.info("Reports grid visible after tab click")
                        return
                except Exception:
                    pass

            # Attempt 2: full page reload to reset CUIC UI state
            # (session cookie persists — no re-login needed)
            self.logger.info("ngGrid hidden after tab click — reloading page")
            self.page.goto(self.url, wait_until='domcontentloaded',
                           timeout=self.timeout_nav)
            self.page.wait_for_timeout(self.timeout_medium)
            self.page.wait_for_selector(self.REPORTS_TAB_CSS,
                                        timeout=self.timeout_nav)
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
    #  WIZARD FIELD READING – CUIC AngularJS-aware
    # ══════════════════════════════════════════════════════════════════════

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

    def _read_wizard_step_fields(self) -> dict | None:
        """Read wizard fields. Tries CUIC Angular scope first, then generic.
        Returns dict with 'type' key: 'cuic_spab' or 'generic'."""
        # ── CUIC path (AngularJS scope) ──
        for f in self.page.frames:
            try:
                result = f.evaluate(self.CUIC_WIZARD_READ_JS)
                if result and result.get('type') == 'cuic_spab':
                    self.logger.debug(f"  CUIC wizard: {len(result.get('params',[]))} param(s)")
                    return result
            except Exception:
                pass

        # ── Generic fallback (standard HTML forms) ──
        all_fields = []
        for f in self.page.frames:
            try:
                result = f.evaluate(self.GENERIC_WIZARD_READ_JS)
                if result:
                    all_fields.extend(result)
            except Exception:
                pass
        return {'type': 'generic', 'fields': all_fields} if all_fields else None

    def _find_wizard_frame(self):
        """Find the frame containing the wizard Next/Run buttons."""
        for f in self.page.frames:
            try:
                for sel in ['button:has-text("Next")', 'input[type="button"][value="Next"]',
                            'button:has-text("Run")',  'input[type="button"][value="Run"]']:
                    btn = f.query_selector(sel)
                    if btn and btn.is_visible():
                        return f
            except Exception:
                pass
        return None

    def _click_wizard_button(self, btn_text: str) -> bool:
        """Click a wizard button (Next / Run / Back) in any frame."""
        for f in self.page.frames:
            try:
                for sel in [f'button:has-text("{btn_text}")',
                            f'input[type="button"][value="{btn_text}"]']:
                    btn = f.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        self.page.wait_for_timeout(self.timeout_short)
                        return True
            except Exception:
                pass
        return False

    def _apply_filters_to_step(self, step_info: dict, saved_values: dict):
        """Apply filter values. Routes to CUIC Angular path or generic DOM path."""
        if not step_info or not saved_values:
            return

        if step_info.get('type') == 'cuic_spab':
            # ── CUIC: apply via Angular scope ──
            cuic_params = {k: v for k, v in saved_values.items()
                          if not k.startswith('_')}
            if not cuic_params:
                return
            for f in self.page.frames:
                try:
                    result = f.evaluate(self.CUIC_WIZARD_APPLY_JS, cuic_params)
                    if result and 'applied' in result:
                        for r in result['applied']:
                            status = 'OK' if r.get('ok') else 'FAIL'
                            self.logger.info(f"    {r.get('param')}: {status} → {r.get('value','')}")
                        return
                except Exception:
                    pass
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
                self.logger.info(f"  Setting filter '{key}' = {val}")
                self._set_field_value(field, val)

    def _set_field_value(self, field: dict, value):
        """Set a standard form field value in the browser (generic fallback)."""
        ftype = field.get('type', 'text')
        fid = field.get('id', '')
        fname = field.get('name', '')
        for f in self.page.frames:
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
                self.logger.debug(f"  Could not set {fid or fname}: {e}")

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 4 – FILTER WIZARD (Next → Next → Run)
    # ══════════════════════════════════════════════════════════════════════
    def _run_filter_wizard(self, filters: dict = None) -> bool:
        """Walk through the wizard steps, applying saved filter values.

        Supported formats:
          CUIC (flat):  {"@start_date": "THISDAY", "@agent_list": "all",
                         "_meta": {"type": "cuic_spab", ...}}
          Step-keyed:   {"step_1": {"field_id": val}, "step_2": {...}}
          Flat generic: {"field_id": val}  (applied to every step)
        """
        try:
            self.page.wait_for_timeout(self.timeout_medium)
            filters = filters or {}

            # Separate metadata from actual filter values
            meta = filters.get('_meta') or {}
            clean = {k: v for k, v in filters.items() if k != '_meta'}
            is_stepped = any(k.startswith('step_') for k in clean)

            step = 0
            max_steps = 10

            while step < max_steps:
                step += 1

                # Read current step's field structure
                step_info = self._read_wizard_step_fields()

                if step_info:
                    stype = step_info.get('type', 'generic')
                    if stype == 'cuic_spab':
                        pnames = [p.get('paramName','') for p in step_info.get('params',[])]
                        self.logger.info(f"  Wizard step {step} (CUIC): {pnames}")
                        # CUIC uses flat param-name keys
                        self._apply_filters_to_step(step_info, clean)
                    elif is_stepped:
                        step_vals = clean.get(f'step_{step}', {})
                        fields = step_info.get('fields', [])
                        labels = [f.get('label') or f.get('id') for f in fields]
                        self.logger.info(f"  Wizard step {step}: {len(fields)} field(s) — {labels}")
                        if step_vals:
                            self._apply_filters_to_step(step_info, step_vals)
                    else:
                        fields = step_info.get('fields', [])
                        labels = [f.get('label') or f.get('id') for f in fields]
                        self.logger.info(f"  Wizard step {step}: {len(fields)} field(s) — {labels}")
                        if clean:
                            self._apply_filters_to_step(step_info, clean)

                    self.page.wait_for_timeout(800)

                # Try Run first (last step), then Next
                if self._click_wizard_button('Run'):
                    self.logger.info(f"  Wizard: clicked Run at step {step}")
                    break
                elif self._click_wizard_button('Next'):
                    self.logger.info(f"  Wizard: clicked Next at step {step}")
                    self.page.wait_for_timeout(self.timeout_short)
                else:
                    self.logger.debug(f"  Wizard step {step}: no Next/Run button")
                    break

            self.page.wait_for_timeout(self.timeout_long)
            self.logger.info("Filter wizard done")
            self.screenshot("03_report_running")
            return True
        except Exception as e:
            self.logger.error(f"Filter wizard failed: {e}")
            self.screenshot("filter_error", is_step=False)
            return False

    # ══════════════════════════════════════════════════════════════════════
    #  WIZARD DISCOVERY (called from settings server)
    # ══════════════════════════════════════════════════════════════════════
    @classmethod
    def discover_wizard(cls, report_config: dict) -> dict:
        """Open a report and read all wizard steps' fields.

        Returns:
          CUIC:    {type: 'cuic_spab', params: [...], datePresets: [...],
                    steps: [{step:1, ...}], error: ''}
          Generic: {type: 'generic', steps: [{step:1, fields:[...]}, ...],
                    error: ''}
        """
        worker = cls()
        worker._load_config()
        folder = report_config.get('folder', '')
        name = report_config.get('name', '')
        result = {'steps': [], 'error': '', 'type': 'generic'}

        try:
            worker.setup_browser(ignore_https_errors=True)

            if not worker._login():
                result['error'] = 'Login failed'
                return result

            frame = worker._get_reports_frame()
            if not frame:
                result['error'] = 'Reports iframe not found'
                return result

            if not worker._open_report(frame, folder, name):
                result['error'] = f'Could not open {folder}/{name}'
                return result

            worker.page.wait_for_timeout(worker.timeout_medium)

            # Walk through wizard steps reading fields
            step = 0
            max_steps = 10
            while step < max_steps:
                step += 1
                step_info = worker._read_wizard_step_fields()

                if step_info:
                    stype = step_info.get('type', 'generic')
                    if stype == 'cuic_spab':
                        # CUIC Angular wizard — return rich param info
                        result['type'] = 'cuic_spab'
                        result['params'] = step_info.get('params', [])
                        result['datePresets'] = step_info.get('datePresets', [])
                        result['steps'].append({
                            'step': step,
                            'type': 'cuic_spab',
                            'params': step_info.get('params', [])
                        })
                    else:
                        # Generic HTML fields
                        result['steps'].append({
                            'step': step,
                            'fields': step_info.get('fields', [])
                        })

                # Check for Run (last step)
                has_run = False
                for f in worker.page.frames:
                    try:
                        for sel in ['button:has-text("Run")', 'input[type="button"][value="Run"]']:
                            btn = f.query_selector(sel)
                            if btn and btn.is_visible():
                                has_run = True
                                break
                        if has_run:
                            break
                    except Exception:
                        pass

                if has_run:
                    # Last step — record fields but don't click Run
                    break

                # Click Next
                if not worker._click_wizard_button('Next'):
                    break
                worker.page.wait_for_timeout(worker.timeout_short)

            worker.logger.info(f"Discovery: {len(result['steps'])} wizard steps found")
            return result

        except Exception as e:
            result['error'] = str(e)
            return result
        finally:
            worker.teardown_browser()

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
