"""
SMAX Report Worker
==================
Generic worker for scraping SMAX report data from the SlickGrid DATA TABLE.
Supports multiple reports configured in settings.json, each with a label, URL,
and optional discovered "report properties" (filters, group-by, function).

Process per report:
    1. Open the report URL
    2. Click the "Table View" button to switch from chart to grid
    3. Read column headers from SlickGrid header row
    4. Read all data rows from SlickGrid viewport
    5. Handle both text cells and checkbox/boolean cells

Performance: Opens ALL reports in parallel tabs, waits once, scrapes all at once.

Discovery:
    The settings server can call discover_properties() to open a report URL,
    read its "Report Properties" sidebar (filters, group-by, function, record
    type, chart info) via AngularJS scope / DOM scraping, and return them as
    structured JSON for display and storage in settings.json.

CSV Output:
    date, timestamp, source, metric_title, category, sub_category, value

Table mapping:
    - 2-column tables (e.g. Phase Id | Count):
        category = col1, sub_category = '', value = col2
    - 3+ column tables (e.g. Month | Phase Id | Count):
        category = col1, sub_category = col2 (extras joined with ' | '), value = last col
"""

import os
import sys
import re
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright
from core.base_worker import BaseWorker
from core.config import get_worker_settings, get_worker_credentials, get_global_settings
from core.database import has_historical_data, log_scrape
from typing import Dict, Any, List, Tuple


class Worker(BaseWorker):
    """
    SMAX Report Scraper (SlickGrid Table-based)

    Reads data from the SlickGrid (pl-grid) data table in each SMAX report.
    Handles tables of any width (2-column, 3-column, etc.).
    Handles both text cells and checkbox/boolean cells.
    """

    SOURCE_NAME = "smax"
    DESCRIPTION = "SMAX Report Scraper - extracts KPIs from report data tables"

    # Timeout settings (milliseconds) — overridden by settings.json
    PAGE_LOAD_TIMEOUT = 120000  # 2 minutes
    ELEMENT_WAIT_TIMEOUT = 30000
    TAB_STAGGER_DELAY = 2000    # ms between opening tabs (avoids server rate-limits)
    MAX_RETRIES = 2             # retry failed tabs this many times

    # Display-value substrings that signal a closed (fully past) time window.
    # Used to auto-detect data_type = 'historical' from report filter properties
    # when the report config does not explicitly set data_type.
    _HISTORICAL_DISPLAY_PATTERNS = frozenset({
        'past year', 'previous year', 'last year',
        'previous month', 'past month', 'last month',
        'previous week', 'past week', 'last week',
        'previous quarter', 'past quarter', 'last quarter',
    })

    # ============================================================
    # SELECTORS
    # ============================================================

    # Button to switch from chart view to table/grid view
    TABLE_VIEW_BUTTON = '[data-aid="report-toggle-Grid"]'
    TABLE_VIEW_FALLBACKS = [
        '[data-aid="report-toggle-Grid"]',     # data-aid (best)
        'button[title="Show Table"]',          # title attribute
        'button:has(i.icon-table)',            # icon class inside button
    ]

    # Report title (in report-area-header)
    TITLE_SELECTOR = '[data-aid="report-name"]'

    # Total row count (in report-area-header)
    TOTAL_SELECTOR = '[data-aid="report-total-count"]'

    # CSS: SlickGrid selectors (scoped to report grid, NOT sidebar grid)
    GRID_HEADER_SELECTOR = 'pl-report-grid .slick-header-column'
    GRID_VIEWPORT_SELECTOR = 'pl-report-grid .slick-viewport'
    GRID_ROW_SELECTOR = 'pl-report-grid .slick-viewport .slick-row'
    GRID_CELL_SELECTOR = '.slick-cell'
    HEADER_NAME_SELECTOR = '.slick-column-name'

    # ============================================================
    # MICROSOFT SSO AUTHENTICATION
    # ============================================================
    # SMAX uses Microsoft Entra ID (SAML SSO). The session is stored
    # as cookies — persists across browser launches when loaded from
    # the saved auth state file.
    SSO_INDICATOR = 'login.microsoftonline.com'  # Domain present in SSO redirect URLs
    SSO_WAIT_TIMEOUT = 300_000                   # 5 minutes for user to complete MFA
    AUTH_STATE_FILE = 'smax_auth_state.json'     # Legacy — kept for backward compat
    CHROME_PROFILE_DIR = 'smax_chrome_profile'   # Persistent Chrome profile under config/
    # ============================================================
    # SMAX REPORT PROPERTIES READER (AngularJS)
    # ============================================================
    # Reads the "Report Properties" sidebar from a loaded SMAX report page.
    # SMAX uses AngularJS with custom directives (pl-filter-field, etc.).
    # This JS reads all properties via stable data-aid attributes and
    # Angular scope API, returning structured JSON.
    SMAX_PROPERTIES_READ_JS = r'''() => {
        const result = {
            report_name: '',
            display_label: '',
            record_type: '',
            filters: [],
            group_by: [],
            func: {},
            chart_function: ''
        };

        /* ── Report Name (visible title at top) ── */
        const nameEl = document.querySelector('[data-aid="report-name"]');
        if (nameEl) result.report_name = nameEl.textContent.trim();

        /* ── Display Label (from properties sidebar - fallback) ── */
        const labelEl = document.querySelector(
            '[data-aid="report-properties-general-tab-content_Name"]'
        );
        if (labelEl && !result.report_name) result.report_name = labelEl.textContent.trim();

        /* ── Record Type ── */
        const rtEl = document.querySelector(
            '[data-aid="report-properties-general-tab-content_EntityType"]'
        );
        if (rtEl) result.record_type = rtEl.textContent.trim();

        /* ── Filters ── */
        const filterFields = document.querySelectorAll(
            'pl-filter-field.platform-filter-field'
        );
        filterFields.forEach(ff => {
            const filter = {};

            // Field name from data-aid="filter_field_XXX"
            const nameSpan = ff.querySelector('span[data-aid^="filter_field_"]');
            if (nameSpan) {
                filter.field_id = nameSpan.getAttribute('data-aid')
                    .replace('filter_field_', '');
                filter.field_label = nameSpan.textContent.trim();
            }

            // Negation operator
            const negSpan = ff.querySelector(
                'span.advance-filter-options-value'
            );
            filter.negated = !!(negSpan &&
                negSpan.textContent.trim().toLowerCase() === 'not');

            // Advance dropdown (Is / Is not) current selection
            const advSelect = ff.querySelector(
                '[data-aid="filter-advance-options-selector"]'
            );
            if (advSelect) {
                const selOpt = advSelect.options[advSelect.selectedIndex];
                filter.operator = selOpt ? selOpt.label || selOpt.text : 'Is';
            } else {
                filter.operator = filter.negated ? 'Is not' : 'Is';
            }

            // Determine filter type and read value
            const dateViewer = ff.querySelector(
                '[data-aid="datetime_filter_viewer"]'
            );
            const ddPredicate = ff.querySelector(
                '[data-control-type="DropDownPredicate"]'
            );
            const entityPicker = ff.querySelector('pl-entity-picker');
            const enumViewer = ff.querySelector(
                '[data-aid="enum_filter_viewer"]'
            );
            const predicateViewer = ff.querySelector(
                '.platform-filter-field-predicate-viewer'
            );

            if (dateViewer) {
                // ── Date filter ──
                filter.type = 'date';
                filter.display_value = dateViewer.getAttribute('title')
                    || dateViewer.textContent.trim();

                // Read available date presets
                const presets = [];
                ff.querySelectorAll(
                    '[data-aid^="date-range-picker-"] a'
                ).forEach(a => {
                    const aid = a.closest('[data-aid]')
                        ?.getAttribute('data-aid') || '';
                    const presetId = aid.replace('date-range-picker-', '');
                    presets.push({
                        id: presetId,
                        label: a.textContent.trim()
                    });
                });
                filter.date_presets = presets;

            } else if (ddPredicate) {
                // ── Dropdown/list filter (e.g. Phase Id) ──
                filter.type = 'dropdown';
                filter.display_value = ddPredicate.textContent.trim();
                // Read selected items from select2 choices
                const choices = [];
                ff.querySelectorAll(
                    '.select2-search-choice div'
                ).forEach(d => {
                    const txt = d.textContent.trim();
                    if (txt) choices.push(txt);
                });
                filter.selected_values = choices.length
                    ? choices : filter.display_value.split(',')
                        .map(s => s.trim()).filter(Boolean);
                // Read hidden input value (IDs)
                const hiddenInput = ff.querySelector(
                    'input[type="hidden"][pl-select2-adapter]'
                );
                if (hiddenInput) {
                    filter.value_ids = hiddenInput.value;
                }

            } else if (entityPicker) {
                // ── Entity picker filter (e.g. Service desk group) ──
                filter.type = 'entity_picker';
                const epChoices = [];
                entityPicker.querySelectorAll(
                    '.select2-search-choice div span'
                ).forEach(sp => {
                    const txt = sp.textContent.trim();
                    if (txt) epChoices.push(txt);
                });
                filter.selected_values = epChoices;
                filter.display_value = epChoices.join(', ');
                const epHidden = entityPicker.querySelector(
                    'input[type="hidden"][pl-select2-adapter]'
                );
                if (epHidden) filter.value_ids = epHidden.value;

            } else if (enumViewer) {
                // ── Enum/checkbox filter (e.g. Current assignment) ──
                filter.type = 'enum';
                filter.display_value = enumViewer.textContent.trim();
                // Read available enum options
                const enumOptions = [];
                ff.querySelectorAll(
                    'pl-multi-select-drop-down .checkboxes li'
                ).forEach(li => {
                    const cb = li.querySelector('input[type="checkbox"]');
                    const span = li.querySelector('span');
                    if (span) {
                        enumOptions.push({
                            id: cb
                                ? cb.getAttribute('data-aid')
                                    ?.replace('flt-cb-id-', '') || ''
                                : '',
                            label: span.textContent.trim(),
                            checked: cb ? cb.checked : false
                        });
                    }
                });
                filter.enum_options = enumOptions;
                filter.selected_values = enumOptions
                    .filter(o => o.checked).map(o => o.label);

            } else if (predicateViewer) {
                // ── Fallback: read plain text value ──
                filter.type = 'text';
                filter.display_value = predicateViewer.textContent.trim();
            }

            if (filter.field_id) result.filters.push(filter);
        });

        /* ── Group By ── */
        const gbContainer = document.querySelector('[data-aid="group-by"]');
        if (gbContainer) {
            gbContainer.querySelectorAll(
                '[data-aid="_mainItemName"]'
            ).forEach(el => {
                const val = el.textContent.trim();
                if (val) result.group_by.push(val);
            });
        }

        /* ── Function ── */
        const fnContainer = document.querySelector('[data-aid="function"]');
        if (fnContainer) {
            const main = fnContainer.querySelector(
                '[data-aid="_mainItemName"]'
            );
            const sec = fnContainer.querySelector(
                '[data-aid="_secondaryItemName"]'
            );
            result.func = {
                main: main ? main.textContent.trim() : '',
                secondary: sec ? sec.textContent.trim() : ''
            };
        }

        /* ── Chart Function ── */
        const cfEl = document.querySelector(
            '[data-aid="report-properties-chart-tab-content_AggregationField"]'
        );
        if (cfEl) result.chart_function = cfEl.textContent.trim();

        /* ── Pie / Chart legend data ── */
        const legendItems = document.querySelectorAll(
            '.nv-legendtab [data-aid="legend-item"]'
        );
        if (legendItems.length) {
            result.chart_legend = [];
            legendItems.forEach(li => {
                const label = li.querySelector('span')?.textContent.trim();
                const value = li.querySelector('em')?.textContent
                    .trim().replace(/[()]/g, '');
                if (label) result.chart_legend.push({ label, value });
            });
        }

        return result;
    }'''  # noqa: E501

    # ============================================================
    # CONFIGURATION
    # ============================================================
    def _load_config(self):
        """Load SMAX config from settings.json + credentials.json."""
        cfg = get_worker_settings('smax')
        cred = get_worker_credentials('smax')

        self.base_url = cfg.get('base_url', 'https://smax.corp.pdo.om')
        self.username = cred.get('username', '')
        self.password = cred.get('password', '')

        # Reports: new per-report format (list of dicts) or legacy URL list
        raw_reports = cfg.get('reports', [])
        if raw_reports and isinstance(raw_reports[0], dict):
            self.reports = raw_reports
        else:
            # Legacy: plain URL list → convert to report dicts
            urls = cfg.get('report_urls', raw_reports or [])
            self.reports = [
                {'label': url.split('/')[-1][:12], 'url': url, 'enabled': True, 'properties': {}}
                for url in urls
            ]

        self.PAGE_LOAD_TIMEOUT = cfg.get('page_load_timeout_ms', 120000)
        self.ELEMENT_WAIT_TIMEOUT = cfg.get('element_wait_timeout_ms', 30000)
        self.TAB_STAGGER_DELAY = cfg.get('tab_stagger_delay_ms', 2000)
        self.MAX_RETRIES = cfg.get('max_retries', 2)
        self._autodetect_data_types()

    def _autodetect_data_types(self):
        """Auto-classify reports as 'historical' based on their filter display values.

        Only fires when 'data_type' is absent from the report config — explicit
        settings ('ongoing' or 'historical') are always respected.
        """
        for report in self.reports:
            if 'data_type' in report:
                continue
            filters = report.get('properties', {}).get('filters', [])
            for f in filters:
                dv = (f.get('display_value') or '').lower()
                if any(pat in dv for pat in self._HISTORICAL_DISPLAY_PATTERNS):
                    report['data_type'] = 'historical'
                    self.logger.debug(
                        f"Auto-detected '{report.get('label')}' as historical "
                        f"(filter '{f.get('field_label')}': {dv!r})"
                    )
                    break

    def run(self) -> List[Dict[str, Any]]:
        """Execute the worker. Opens all reports in parallel tabs for speed.

        Authentication:
        - Uses a persistent Chrome profile (config/smax_chrome_profile/).
        - Microsoft SSO session is stored natively by Chrome — persists across
          restarts without any JSON tricks.
        - First run (or after session expiry): restarts in headed mode so the
          user can complete Microsoft sign-in + MFA. Subsequent runs are silent.
        """
        self._load_config()

        enabled = [r for r in self.reports if r.get('enabled', True)]
        if not enabled:
            self.logger.warning("No enabled SMAX reports configured.")
            log_scrape('smax', '_worker', 'no_data', 0, 0, 'No enabled reports configured')
            return []

        result = []
        try:
            # ── Step 1: Start browser with persistent profile ──────────
            self.setup_browser()

            # ── Step 2: Check whether the session is still valid ───────
            if not self._ensure_authenticated():
                self.logger.info("Session expired — re-authenticating via Microsoft SSO (headed)")
                self.teardown_browser()
                self.setup_browser(headless=False)
                self._wait_for_sso_auth()

                # _wait_for_sso_auth() confirmed the browser left the SSO domain.
                # Check current URL instead of navigating again (another goto()
                # would trigger a new SAML round-trip).
                current_url = self.page.url
                if self.SSO_INDICATOR in current_url:
                    raise RuntimeError("Authentication failed after Microsoft SSO attempt")
                self.logger.info(f"Post-SSO verification OK (URL: {current_url[:80]})")

            # ── Step 3: Scrape ─────────────────────────────────────────
            result = self.scrape()

        except Exception as e:
            self.logger.error(f"Worker failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            log_scrape('smax', '_worker', 'error', 0, 0, str(e))
        finally:
            self.teardown_browser()

        return result

    def scrape(self) -> List[Dict[str, Any]]:
        """
        Scrape all SMAX reports using parallel tabs with staggered opening.

        Flow:
        1. Open all tabs with stagger delay
        2. For each tab: click "Table View" button, wait for grid to render
        3. Retry any tabs that failed
        4. Scrape grid data from each tab
        5. Clean up extra tabs
        """
        all_results = []
        tabs = []  # List of (page, report_cfg) tuples

        enabled = [r for r in self.reports if r.get('enabled', True)]
        start_time = time.time()

        # ---- PHASE 1: Open tabs with stagger delay ----
        self.logger.info(f"Opening {len(enabled)} reports in tabs (stagger={self.TAB_STAGGER_DELAY}ms)...")

        for i, report in enumerate(enabled):
            url = report.get('url', '')
            label = report.get('label', url.split('/')[-1] if url else f'report_{i}')
            if not url:
                self.logger.warning(f"  Report {i+1}: no URL configured, skipping")
                continue

            # Skip historical reports that already have data
            if report.get('data_type') == 'historical':
                if has_historical_data('smax', label):
                    self.logger.info(f"  Report {i+1} '{label}': HISTORICAL - already scraped, skipping")
                    log_scrape('smax', label, 'skipped', 0, 0, 'Historical data already exists')
                    continue

            try:
                if i == 0:
                    tab = self.page
                else:
                    # Wait BEFORE creating the new page so the blank tab is
                    # never visible for the full stagger delay.
                    self.page.wait_for_timeout(self.TAB_STAGGER_DELAY)
                    tab = self.context.new_page()

                tab.goto(url, wait_until='commit', timeout=self.PAGE_LOAD_TIMEOUT)
                tabs.append((tab, report))
                self.logger.info(f"  Tab {i+1}: navigation started -> {label}")

            except Exception as e:
                self.logger.error(f"  Tab {i+1}: failed to open {url}: {e}")
                log_scrape('smax', label, 'error', 0, 0, f'Tab open failed: {e}')

        self.logger.info(f"All {len(tabs)} tabs opened in {time.time() - start_time:.1f}s")
        
        # ---- PHASE 2: Switch each tab to table view and wait for grid ----
        self.logger.info("Switching all tabs to table view...")

        failed_tabs = []

        for i, (tab, report) in enumerate(tabs):
            try:
                self._switch_to_table_view(tab)
                self.logger.info(f"  Tab {i+1}: grid ready")
            except Exception as e:
                self.logger.warning(f"  Tab {i+1}: not ready, queued for retry ({e})")
                failed_tabs.append(i)

        # ---- PHASE 2b: Retry failed tabs ----
        for attempt in range(1, self.MAX_RETRIES + 1):
            if not failed_tabs:
                break

            self.logger.info(f"Retrying {len(failed_tabs)} failed tab(s) (attempt {attempt}/{self.MAX_RETRIES})...")
            still_failed = []

            for idx in failed_tabs:
                tab, report = tabs[idx]
                url = report.get('url', '')
                try:
                    self.logger.info(f"  Tab {idx+1}: reloading {report.get('label', url.split('/')[-1])}...")
                    try:
                        tab.goto(url, wait_until='commit', timeout=self.PAGE_LOAD_TIMEOUT)
                    except Exception as e:
                        if not tab.url or tab.url == 'about:blank':
                            raise
                        self.logger.debug(f"  Tab {idx+1}: goto raised (expected SAML): {e}")
                    self._switch_to_table_view(tab)
                    self.logger.info(f"  Tab {idx+1}: ready after retry")
                except Exception as e:
                    self.logger.warning(f"  Tab {idx+1}: retry failed: {e}")
                    still_failed.append(idx)

            failed_tabs = still_failed

        if failed_tabs:
            failed_labels = []
            for i in failed_tabs:
                lbl = tabs[i][1].get('label', '?')
                failed_labels.append(lbl)
                log_scrape('smax', lbl, 'error', 0, 0, 'Tab failed after all retries')
            self.logger.warning(f"{len(failed_tabs)} tab(s) still failed: {failed_labels}")
        
        # Wait for grid to be ready rather than arbitrary timeout
        try:
            tabs[0][0].locator(self.GRID_ROW_SELECTOR).first.wait_for(
                state='visible', timeout=5000)
        except Exception:
            pass  # Best-effort; scraping will fail clearly if grid isn't ready
        
        self.logger.info(f"All tabs ready in {time.time() - start_time:.1f}s")
        
        # ---- PHASE 3: Scrape data from each tab ----
        self.logger.info("Scraping data from all tabs...")

        for i, (tab, report) in enumerate(tabs):
            url = report.get('url', '')
            label = report.get('label', url.split('/')[-1] if url else f'report_{i}')
            t0 = time.time()
            try:
                report_data = self._extract_from_page(tab, url, label)
                elapsed = time.time() - t0
                if report_data:
                    all_results.extend(report_data)
                    log_scrape('smax', label, 'success', len(report_data), elapsed, '')
                else:
                    log_scrape('smax', label, 'no_data', 0, elapsed, 'No data returned')
            except Exception as e:
                elapsed = time.time() - t0
                self.logger.error(f"  Tab {i+1}: scrape failed for {label}: {e}")
                log_scrape('smax', label, 'error', 0, elapsed, str(e))

        # ---- PHASE 4: Clean up extra tabs ----
        for i, (tab, report) in enumerate(tabs):
            if i > 0:
                try:
                    tab.close()
                except Exception:
                    pass

        # Close any stray about:blank tabs that appeared mid-scrape
        for p in self.context.pages:
            if p != self.page and p.url == 'about:blank':
                try:
                    p.close()
                except Exception:
                    pass

        total_time = time.time() - start_time
        self.logger.info(f"Scraping complete: {len(all_results)} metrics from "
                         f"{len(tabs)} reports in {total_time:.1f}s")

        return all_results
    
    # ============================================================
    # Tab Preparation
    # ============================================================
    
    def _switch_to_table_view(self, page):
        """
        Click the 'Table View' button and wait for the SlickGrid to render.
        Uses a fallback chain of selectors for resilience.

        Args:
            page: Playwright Page object
        """
        for sel in self.TABLE_VIEW_FALLBACKS:
            try:
                btn = page.locator(sel).first
                # wait_for() blocks until the button is in the DOM — this gives
                # Angular time to bootstrap. Do NOT use count() here: count() is
                # an instant synchronous check that returns 0 before Angular loads,
                # causing all fallbacks to be skipped before any waiting happens.
                btn.wait_for(state='visible', timeout=self.ELEMENT_WAIT_TIMEOUT)
                btn.click()
                # Wait for SlickGrid rows to render after the view switch
                page.locator(self.GRID_ROW_SELECTOR).first.wait_for(
                    state='visible', timeout=self.ELEMENT_WAIT_TIMEOUT)
                self.logger.info(f"  Table view activated via: {sel}")
                return
            except Exception:
                continue
        raise Exception("Table View button not found with any selector")
    
    # ============================================================
    # Data Extraction
    # ============================================================
    
    def _extract_from_page(self, page, url: str, label: str = '') -> List[Dict[str, Any]]:
        """
        Extract report title, total, and all table rows from a loaded page.
        
        Table mapping:
            - Last column is always the value (numeric)
            - First column -> category
            - Middle columns (if any) -> sub_category (joined with ' | ')
        """
        results = []
        report_id = url.split('/')[-1][:12]
        
        # Get report title; fall back to the config label when the DOM element
        # is missing (partial page load) so rows are still identifiable.
        report_title = self._get_report_title(page)
        if report_title == "Unknown Report" and label:
            report_title = label
        total_rows = self._get_total_rows(page)

        self.logger.info(f"  [{report_id}] {report_title}: total={total_rows}")

        # Skip if page didn't load properly (no title found and no data)
        if report_title == "Unknown Report" and total_rows == 0:
            self.logger.warning(f"  [{report_id}] Skipping: Unknown Report with 0 total (page may not have loaded)")
            return results

        # Add the total as its own row
        results.append({
            'metric_title': report_title,
            'category': 'total',
            'sub_category': '',
            'value': total_rows
        })
        
        # Read the SlickGrid table
        headers, data_rows = self._read_grid(page)
        
        if not headers or not data_rows:
            self.logger.warning(f"  [{report_id}] No grid data found")
            return results
        
        self.logger.info(f"  [{report_id}] Headers: {headers}")
        self.logger.info(f"  [{report_id}] {len(data_rows)} data row(s)")
        
        num_cols = len(headers)
        
        for row in data_rows:
            if len(row) < 2:
                continue
            
            if num_cols == 1:
                # Single column - just a value, use header as category
                category = headers[0]
                sub_category = ''
                value = self._parse_value(row[0])
            elif num_cols == 2:
                # [label, value] -> category=label, sub_category='', value=value
                category = row[0]
                sub_category = ''
                value = self._parse_value(row[1])
            else:
                # [label1, label2, ..., value]
                # category=label1, sub_category=remaining labels, value=last
                category = row[0]
                sub_category = ' | '.join(row[1:-1])
                value = self._parse_value(row[-1])
            
            results.append({
                'metric_title': report_title,
                'category': category,
                'sub_category': sub_category,
                'value': value
            })
            
            sub_str = f" / {sub_category}" if sub_category else ""
            self.logger.info(f"  [{report_id}]   {category}{sub_str}: {value}")
        
        return results
    
    def _read_grid(self, page) -> Tuple[List[str], List[List[str]]]:
        """
        Read headers and data from the SlickGrid report table with scrolling support.
        
        Returns:
            Tuple of (headers: List[str], rows: List[List[str]])
        """
        # ---- Read column headers ----
        header_els = page.query_selector_all(self.GRID_HEADER_SELECTOR)
        
        headers = []
        header_indices = []  # Track which cell indices have real data columns
        
        for i, el in enumerate(header_els):
            name_el = el.query_selector(self.HEADER_NAME_SELECTOR)
            name = name_el.text_content().strip() if name_el else ''
            if name:
                headers.append(name)
                header_indices.append(i)
        
        if not headers:
            self.logger.warning("No grid headers found")
            return [], []
        
        # ---- Read data rows with scrolling ----
        collected_rows = []
        seen_keys = set()
        
        # Check if viewport exists for scrolling
        if not page.query_selector(self.GRID_VIEWPORT_SELECTOR):
            return headers, self._read_visible_rows(page, header_indices)
            
        # Scroll loop
        no_new_data_count = 0
        at_bottom_count = 0
        max_scrolls = 200
        scroll_count = 0
        
        self.logger.info("  Starting scroll loop...")
        
        while scroll_count < max_scrolls:
            scroll_count += 1
            
            # 1. Read currently visible rows
            current_rows = self._read_visible_rows(page, header_indices)
            
            added_this_loop = 0
            for row in current_rows:
                key = tuple(row)
                if key not in seen_keys:
                    seen_keys.add(key)
                    collected_rows.append(row)
                    added_this_loop += 1
            
            if added_this_loop > 0:
                no_new_data_count = 0
                at_bottom_count = 0  # Reset bottom counter if we found data (size might have grown)
            else:
                no_new_data_count += 1
                
            if no_new_data_count >= 10:
                self.logger.info("  Stopping scroll: No new data found for 10 consecutive attempts")
                break
            
            # 2. Scroll down and get dimensions
            scroll_info = page.evaluate("""selector => {
                const el = document.querySelector(selector);
                if (!el) return null;
                const prevTop = el.scrollTop;
                // Scroll down by clientHeight (one page)
                el.scrollTop += el.clientHeight;
                el.dispatchEvent(new Event('scroll'));
                return {
                    moved: el.scrollTop > prevTop,
                    scrollTop: el.scrollTop,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    atBottom: (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 1)
                };
            }""", self.GRID_VIEWPORT_SELECTOR)
            
            # Log progress
            if scroll_count % 10 == 0:
                self.logger.info(f"  Scroll {scroll_count}: {len(collected_rows)} rows. Info: {scroll_info}")

            if not scroll_info:
                 self.logger.warning("  Scroll target element not found")
                 break

            # Check if we are stuck at the bottom
            if not scroll_info['moved'] or scroll_info['atBottom']:
                at_bottom_count += 1
                # If we are at the bottom, we wait a bit longer to see if infinite scroll loads more
                if at_bottom_count >= 5:
                    self.logger.info(f"  Stopping scroll: Stuck at bottom for {at_bottom_count} attempts. Total rows: {len(collected_rows)}")
                    break
            else:
                at_bottom_count = 0
                
            # SlickGrid virtual scroll render buffer — no DOM event to wait for
            page.wait_for_timeout(500)
            
        return headers, collected_rows

    def _read_visible_rows(self, page, header_indices) -> List[List[str]]:
        """Read currently DOM-rendered rows."""
        row_els = page.query_selector_all(self.GRID_ROW_SELECTOR)
        if not row_els:
            return []
            
        data_rows = []
        for row_el in row_els:
            cells = row_el.query_selector_all(self.GRID_CELL_SELECTOR)
            
            cell_values = []
            for idx in header_indices:
                if idx < len(cells):
                    val = self._read_cell_value(cells[idx])
                    cell_values.append(val)
                else:
                    cell_values.append('')
            
            if cell_values:
                data_rows.append(cell_values)
        return data_rows
    
    def _read_cell_value(self, cell) -> str:
        """
        Read the display value from a SlickGrid cell.
        
        Handles multiple cell types:
        1. Boolean/checkbox cells: look for li > label > span pattern
        2. Percentage cells: preserve % symbol from display text
        3. Text cells: read all visible text content
        
        Uses text_content() instead of inner_text() to capture ALL text,
        including percentage symbols that might be in separate elements.
        """
        # First check for the checkbox/boolean pattern: li > label > span
        # (This is how SMAX renders boolean fields in the grid)
        label_span = cell.query_selector('li label span')
        if label_span:
            # Try to read text from the span (might be ✓, ☐, etc.)
            text = label_span.text_content().strip()
            if text:
                return text
            
            # If span text is empty, check for a checkbox input
            checkbox = cell.query_selector('input[type="checkbox"]')
            if checkbox:
                return 'true' if checkbox.is_checked() else 'false'
            
            # Fallback: check the label/span class for indicators
            cls = label_span.get_attribute('class') or ''
            if any(x in cls.lower() for x in ['check', 'active', 'selected']):
                return 'true'
            return 'false'
        
        # Also check for standalone checkbox (no li/label wrapper)
        checkbox = cell.query_selector('input[type="checkbox"]')
        if checkbox:
            return 'true' if checkbox.is_checked() else 'false'
        
        # Standard text cell — use text_content() to capture ALL text including % symbols
        # text_content() captures text from all child nodes, even if % is in a separate span
        return cell.text_content().strip()
    
    # ============================================================
    # Header Extraction (Title & Total)
    # ============================================================
    
    def _get_report_title(self, page=None) -> str:
        """Extract the report title from the report-area-header."""
        if page is None:
            page = self.page
        try:
            el = page.query_selector(self.TITLE_SELECTOR)
            if el:
                text = el.text_content().strip()
                if text and text != 'No columns to select':
                    return text
            return "Unknown Report"
        except Exception as e:
            self.logger.warning(f"Could not get report title: {e}")
            return "Unknown Report"
    
    def _get_total_rows(self, page=None) -> int:
        """Extract the total row count from the report-area-header."""
        if page is None:
            page = self.page
        try:
            el = page.query_selector(self.TOTAL_SELECTOR)
            if el:
                text = el.text_content().strip()
                parsed = self._parse_number(text)
                if parsed > 0:
                    return parsed
            return 0
        except Exception as e:
            self.logger.warning(f"Could not get total rows: {e}")
            return 0
    
    # ============================================================
    # Parsers
    # ============================================================
    
    def _parse_number(self, text: str) -> int:
        """Parse integer from text like '1,234 records' -> 1234"""
        try:
            numbers = re.findall(r'\d+', text.replace(',', ''))
            return int(numbers[0]) if numbers else 0
        except Exception:
            return 0
    
    def _parse_value(self, text: str) -> float:
        """
        Parse a numeric value from a table cell.
        Handles: '151', '9.51%', '1,234', '(90.49)', etc.
        Returns the original text if not numeric (for label columns).
        """
        try:
            cleaned = text.strip().strip('()%').replace(',', '').strip()
            match = re.search(r'[\d.]+', cleaned)
            if match:
                num = float(match.group())
                return int(num) if num == int(num) else num
            return 0
        except Exception:
            return 0
    
    # ============================================================
    # MICROSOFT SSO SESSION MANAGEMENT
    # ============================================================

    def _auth_state_path(self) -> str:
        """Absolute path to the stored Microsoft SSO session state file (legacy)."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, 'config', self.AUTH_STATE_FILE)

    def _profile_dir(self) -> str:
        """Absolute path to Chrome user data directory. Created on first run."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, 'config', self.CHROME_PROFILE_DIR)

    def setup_browser(self, headless: bool = None, storage_state: str = None, **kwargs):
        """Override base class to use a persistent Chrome profile.

        With launch_persistent_context() Chrome stores cookies, localStorage,
        and all session data in a real on-disk profile directory. Microsoft SSO
        sessions survive browser restarts — no JSON storage_state tricks needed.

        The storage_state parameter is accepted but ignored (kept for signature
        compatibility with base_worker callers).
        """
        cfg = get_global_settings()
        if headless is None:
            headless = cfg.get('headless', True)
        self._screenshot_steps = cfg.get('screenshot_steps', False)
        self._screenshot_errors = cfg.get('screenshot_errors', True)

        profile_dir = self._profile_dir()
        os.makedirs(profile_dir, exist_ok=True)
        self.logger.info(f"Chrome profile: {profile_dir}")

        # Remove stale Chrome lock files that can cause ERR_ABORTED on launch.
        # These are left behind when Chrome is force-killed or crashes.
        for lock in ('SingletonLock', 'SingletonSocket', '.parentlock'):
            lock_path = os.path.join(profile_dir, lock)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                    self.logger.debug(f"Removed stale lock: {lock}")
                except Exception:
                    pass

        self._playwright = sync_playwright().start()
        # launch_persistent_context returns BrowserContext directly — no Browser object
        self.context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=headless,
            channel='chrome',
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--ignore-certificate-errors',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-infobars',
                '--disable-session-crashed-bubble',
                '--restore-last-session=false',
            ],
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            ignore_https_errors=True,
        )
        self.browser = None  # No separate Browser object with persistent context
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # Close any extra pages Chrome may have restored from the persistent profile
        for extra_page in self.context.pages:
            if extra_page != self.page:
                try:
                    extra_page.close()
                except Exception:
                    pass

        self.logger.info("Browser initialized successfully")
        return self.page

    def teardown_browser(self):
        """Persistent context teardown — skips browser.close() (no separate browser)."""
        for name, obj, method in [
            ("page",       self.page,         "close"),
            ("context",    self.context,      "close"),
            ("playwright", self._playwright,  "stop"),
        ]:
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception as e:
                    self.logger.warning(f"Error closing {name}: {e}")
        self.page = None
        self.context = None
        self.browser = None
        self._playwright = None
        self.logger.info("Browser closed successfully")

    def _ensure_authenticated(self) -> bool:
        """Navigate to base URL and check whether Microsoft SSO intercepts.

        SMAX uses SAML SP-initiated SSO, so even a valid session briefly passes
        through login.microsoftonline.com before landing back on SMAX. This method
        waits up to 15 s for that round-trip to complete before deciding.

        Returns True if landed on SMAX, False if stuck on SSO after the timeout.
        """
        try:
            # Use 'commit' instead of 'domcontentloaded': SMAX's SAML flow involves
            # a JavaScript form.submit() that starts a secondary navigation. Playwright
            # marks the original goto as ERR_ABORTED when that secondary navigation
            # starts. 'commit' fires on the first server response and avoids this.
            try:
                self.page.goto(self.base_url, wait_until='commit', timeout=30000)
            except Exception as e:
                # ERR_ABORTED is expected during SAML redirect chains; the browser has
                # already navigated somewhere — check the URL before giving up.
                current = self.page.url
                self.logger.debug(f"goto raised during auth check (url={current[:60]}): {e}")
                if not current or current == 'about:blank':
                    self.logger.warning(f"Auth check failed — blank page after goto: {e}")
                    return False
            # Wait for the SAML round-trip to resolve (SMAX -> Microsoft -> SMAX).
            # If the session is valid the browser returns to SMAX within a few seconds.
            # If the session is expired it stays on Microsoft's login page.
            try:
                self.page.wait_for_function(
                    f'() => !window.location.href.includes("{self.SSO_INDICATOR}")',
                    timeout=15000
                )
                url = self.page.url
                self.logger.info(f"Authenticated (URL: {url[:80]})")
                return True
            except Exception:
                url = self.page.url
                self.logger.info(f"SSO redirect detected (not authenticated): {url[:80]}")
                return False
        except Exception as e:
            self.logger.warning(f"Auth check failed: {e}")
            return False

    def _wait_for_sso_auth(self):
        """Open SMAX and wait for the user to complete Microsoft SSO + MFA.

        The browser MUST be in headed mode at this point. Once the browser URL
        returns to the SMAX domain, saves the context state for future runs.
        """
        self.logger.info("=" * 60)
        self.logger.info("MICROSOFT SSO AUTHENTICATION REQUIRED")
        self.logger.info("A browser window has opened — please log in.")
        self.logger.info("Complete the Microsoft sign-in (including MFA if prompted).")
        self.logger.info(f"Waiting up to {self.SSO_WAIT_TIMEOUT // 60000} minutes...")
        self.logger.info("=" * 60)

        # Navigate to SMAX — the SAML SP will redirect to Microsoft login.
        # ERR_ABORTED is expected here: SMAX's SAML redirect chain includes a
        # JavaScript form.submit() which starts a secondary navigation. Playwright
        # marks the original goto as aborted when that secondary navigation fires.
        # This is NOT a real failure — the browser has navigated to the login page.
        try:
            self.page.goto(self.base_url, wait_until='commit', timeout=30000)
        except Exception as e:
            current = self.page.url
            self.logger.debug(f"goto raised (expected during SAML redirect, url={current[:60]}): {e}")
            if not current or current == 'about:blank':
                # Truly blank page — something is wrong
                raise RuntimeError(f"Browser did not navigate: {e}") from e

        # At this point the browser is somewhere in the SSO flow.
        # Log where we landed so the user can see the browser is working.
        self.logger.info(f"Browser navigated to: {self.page.url[:80]}")

        # Wait until the browser leaves the Microsoft SSO domain
        self.page.wait_for_function(
            f'() => !window.location.href.includes("{self.SSO_INDICATOR}")',
            timeout=self.SSO_WAIT_TIMEOUT
        )

        # Allow SMAX to finish loading after the final SSO redirect
        try:
            self.page.wait_for_load_state('networkidle', timeout=30000)
        except Exception:
            pass

        self.logger.info("SSO authentication completed.")
        self._save_auth_state()

    def _save_auth_state(self):
        """No-op: session is stored automatically in the persistent Chrome profile."""
        self.logger.info("Session stored in persistent Chrome profile.")

    def _login_if_needed(self):
        """Legacy form-based login — no longer active.

        SMAX now uses Microsoft Entra ID (SAML SSO). Session management is
        handled by _ensure_authenticated() / _wait_for_sso_auth() in run().
        This stub is kept to avoid breaking any external callers.
        """
        pass



    # ============================================================
    # REPORT PROPERTIES DISCOVERY (called from settings server)
    # ============================================================
    @classmethod
    def discover_properties(cls, report_config: dict) -> dict:
        """Open a report URL and read its Report Properties sidebar.

        Args:
            report_config: dict with at least 'url' key, optionally
                           'base_url', 'username', 'password'.

        Returns:
            dict with keys: report_name, display_label, record_type, filters,
            group_by, func, chart_function, chart_legend, error
        """
        worker = cls()
        worker._load_config()

        url = report_config.get('url', '')
        if not url:
            return {'error': 'No report URL provided'}

        result = {'error': ''}

        try:
            # Use persistent Chrome profile — same SSO flow as run()
            worker.setup_browser()

            if not worker._ensure_authenticated():
                worker.logger.info("Discovery: SSO auth required — opening headed browser")
                worker.teardown_browser()
                worker.setup_browser(headless=False)
                worker._wait_for_sso_auth()

            worker.logger.info(f"Discovery: navigating to {url}")
            # Use 'commit' to avoid ERR_ABORTED from SAML redirect chains.
            # If the session is valid SMAX loads; if expired we'll land on SSO.
            try:
                worker.page.goto(url, wait_until='commit',
                                 timeout=worker.PAGE_LOAD_TIMEOUT)
            except Exception as e:
                current = worker.page.url
                worker.logger.debug(f"goto raised during discovery (url={current[:60]}): {e}")
                if not current or current == 'about:blank':
                    raise

            # If we ended up on the SSO page the session expired mid-run.
            if worker.SSO_INDICATOR in worker.page.url:
                raise RuntimeError(
                    'Session expired. Close this dialog and run discovery again '
                    'to complete the Microsoft login.'
                )

            # Wait for the properties panel to render
            try:
                worker.page.wait_for_selector(
                    '[data-aid="report-properties"]',
                    timeout=worker.ELEMENT_WAIT_TIMEOUT
                )
            except Exception:
                # Sidebar might already be open or have a different wrapper
                worker.logger.info("Properties sidebar selector not found, "
                                   "trying to read properties anyway")

            # Wait for AngularJS to finish rendering before reading properties
            try:
                worker.page.wait_for_function(
                    '''() => {
                        try {
                            if (typeof angular === 'undefined') return true;
                            const pending = angular.element(document).injector().get('$http').pendingRequests;
                            return pending.length === 0;
                        } catch(e) { return true; }
                    }''',
                    timeout=10000
                )
            except Exception:
                worker.logger.debug("Angular wait timed out, proceeding anyway")

            # Read properties via injected JS
            props = worker.page.evaluate(worker.SMAX_PROPERTIES_READ_JS)

            if props:
                result.update(props)
                filter_count = len(props.get('filters', []))
                worker.logger.info(
                    f"Discovery: found {filter_count} filter(s), "
                    f"record_type={props.get('record_type','')}, "
                    f"report_name={props.get('report_name','')}"
                )
            else:
                result['error'] = 'Could not read report properties from page'

        except Exception as e:
            result['error'] = str(e)
            worker.logger.error(f"Discovery failed: {e}")
        finally:
            worker.teardown_browser()

        return result


# For testing the worker directly
if __name__ == '__main__':
    print("Testing SMAX Worker...")
    worker = Worker()
    results = worker.run()
    print(f"\n{len(results)} metrics scraped:")
    for r in results:
        sub = f" / {r['sub_category']}" if r.get('sub_category') else ""
        print(f"  {r['metric_title']} | {r['category']}{sub}: {r['value']}")
