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

from core.base_worker import BaseWorker
from core.config import get_worker_settings, get_worker_credentials
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
    
    # ============================================================
    # SELECTORS
    # ============================================================

    # XPath: Button to switch from chart view to table/grid view
    TABLE_VIEW_BUTTON = 'xpath=/html/body/div[1]/div/div[2]/div[2]/div/div/div/div/div[3]/div[1]/span/button[2]'

    # XPath: Report title (span[3] in header)
    TITLE_XPATH = 'xpath=/html/body/div[1]/div/div[2]/div[2]/div/div/div/div/div[1]/div/span[3]'

    # XPath: Total row count (span[1] in header)
    TOTAL_XPATH = 'xpath=/html/body/div[1]/div/div[2]/div[2]/div/div/div/div/div[1]/div/span[1]'

    # CSS: SlickGrid selectors (scoped to report grid, NOT sidebar grid)
    GRID_HEADER_SELECTOR = 'pl-report-grid .slick-header-column'
    GRID_VIEWPORT_SELECTOR = 'pl-report-grid .slick-viewport'
    GRID_ROW_SELECTOR = 'pl-report-grid .slick-viewport .slick-row'
    GRID_CELL_SELECTOR = '.slick-cell'
    HEADER_NAME_SELECTOR = '.slick-column-name'

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

        /* ── Report Name ── */
        const nameEl = document.querySelector(
            '[data-aid="report-properties-general-tab-content_Name"]'
        );
        if (nameEl) result.report_name = nameEl.textContent.trim();

        /* ── Display Label ── */
        const labelEl = document.querySelector(
            'span[ng-controller="multiLangEditorViewerCtrl"]'
        );
        if (labelEl) result.display_label = labelEl.textContent.trim();

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

    def run(self) -> List[Dict[str, Any]]:
        """Execute the worker. Opens all reports in parallel tabs for speed."""
        self._load_config()

        enabled = [r for r in self.reports if r.get('enabled', True)]
        if not enabled:
            self.logger.warning("No enabled SMAX reports configured.")
            return []

        result = []
        try:
            self.setup_browser()

            if self.username and self.password:
                self.logger.info("Attempting SMAX login...")
                self._login_if_needed()
            else:
                self.logger.warning("No SMAX credentials configured - attempting without login")

            result = self.scrape()

        except Exception as e:
            self.logger.error(f"Worker failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
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
            if not url:
                self.logger.warning(f"  Report {i+1}: no URL configured, skipping")
                continue
            try:
                if i == 0:
                    tab = self.page
                else:
                    tab = self.context.new_page()
                    self.page.wait_for_timeout(self.TAB_STAGGER_DELAY)

                tab.goto(url, wait_until='commit', timeout=self.PAGE_LOAD_TIMEOUT)
                tabs.append((tab, report))
                self.logger.info(f"  Tab {i+1}: navigation started -> {report.get('label', url.split('/')[-1])}")

            except Exception as e:
                self.logger.error(f"  Tab {i+1}: failed to open {url}: {e}")

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
                    tab.goto(url, wait_until='domcontentloaded', timeout=self.PAGE_LOAD_TIMEOUT)
                    self._switch_to_table_view(tab)
                    self.logger.info(f"  Tab {idx+1}: ready after retry")
                except Exception as e:
                    self.logger.warning(f"  Tab {idx+1}: retry failed: {e}")
                    still_failed.append(idx)

            failed_tabs = still_failed

        if failed_tabs:
            self.logger.warning(f"{len(failed_tabs)} tab(s) still failed: "
                                f"{[tabs[i][1].get('label','?') for i in failed_tabs]}")
        
        # Small buffer for final rendering
        tabs[0][0].wait_for_timeout(2000)
        
        self.logger.info(f"All tabs ready in {time.time() - start_time:.1f}s")
        
        # ---- PHASE 3: Scrape data from each tab ----
        self.logger.info("Scraping data from all tabs...")

        for i, (tab, report) in enumerate(tabs):
            url = report.get('url', '')
            try:
                report_data = self._extract_from_page(tab, url)
                all_results.extend(report_data)
            except Exception as e:
                self.logger.error(f"  Tab {i+1}: scrape failed for {report.get('label', url)}: {e}")

        # ---- PHASE 4: Clean up extra tabs ----
        for i, (tab, report) in enumerate(tabs):
            if i > 0:
                try:
                    tab.close()
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
        
        Args:
            page: Playwright Page object
        """
        # Wait for the table-view button to appear (page loaded enough)
        page.wait_for_selector(self.TABLE_VIEW_BUTTON, timeout=self.ELEMENT_WAIT_TIMEOUT)
        
        # Click to switch from chart to table/grid view
        page.click(self.TABLE_VIEW_BUTTON)
        
        # Wait for grid data rows to appear
        page.wait_for_selector(self.GRID_ROW_SELECTOR, timeout=self.ELEMENT_WAIT_TIMEOUT)
    
    # ============================================================
    # Data Extraction
    # ============================================================
    
    def _extract_from_page(self, page, url: str) -> List[Dict[str, Any]]:
        """
        Extract report title, total, and all table rows from a loaded page.
        
        Table mapping:
            - Last column is always the value (numeric)
            - First column -> category
            - Middle columns (if any) -> sub_category (joined with ' | ')
        """
        results = []
        report_id = url.split('/')[-1][:12]
        
        # Get report title and total
        report_title = self._get_report_title(page)
        total_rows = self._get_total_rows(page)
        
        self.logger.info(f"  [{report_id}] {report_title}: total={total_rows}")
        
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
            name = name_el.inner_text().strip() if name_el else ''
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
                
            # Wait for render (SlickGrid is virtual)
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
        
        Handles two cell types:
        1. Text cells: just read inner_text()
        2. Boolean/checkbox cells: look for li > label > span pattern
           (SMAX renders booleans as checkbox icons inside this structure)
        """
        # First check for the checkbox/boolean pattern: li > label > span
        # (This is how SMAX renders boolean fields in the grid)
        label_span = cell.query_selector('li label span')
        if label_span:
            # Try to read text from the span (might be ✓, ☐, etc.)
            text = label_span.inner_text().strip()
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
        
        # Standard text cell — just read the text
        return cell.inner_text().strip()
    
    # ============================================================
    # Header Extraction (Title & Total)
    # ============================================================
    
    def _get_report_title(self, page=None) -> str:
        """Extract the report title from span[3] in the header."""
        if page is None:
            page = self.page
        try:
            el = page.query_selector(self.TITLE_XPATH)
            if el:
                text = el.inner_text().strip()
                if text and text != 'No columns to select':
                    return text
            return "Unknown Report"
        except Exception as e:
            self.logger.warning(f"Could not get report title: {e}")
            return "Unknown Report"
    
    def _get_total_rows(self, page=None) -> int:
        """Extract the total row count from span[1] in the header."""
        if page is None:
            page = self.page
        try:
            el = page.query_selector(self.TOTAL_XPATH)
            if el:
                text = el.inner_text().strip()
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
    # Authentication
    # ============================================================

    def _login_if_needed(self):
        """Perform SMAX login if credentials are configured."""
        if not self.username or not self.password:
            return

        self.page.goto(f"{self.base_url}/login", wait_until='networkidle')

        if 'login' not in self.page.url.lower():
            self.logger.info("Already logged in to SMAX")
            return

        self.login_with_form(
            url=f"{self.base_url}/login",
            username=self.username,
            password=self.password,
            username_selector='#username',
            password_selector='#password',
            submit_selector='button[type="submit"]',
            success_indicator='.dashboard, .main-content'
        )

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
            worker.setup_browser()

            if worker.username and worker.password:
                worker._login_if_needed()

            worker.logger.info(f"Discovery: navigating to {url}")
            worker.page.goto(url, wait_until='domcontentloaded',
                             timeout=worker.PAGE_LOAD_TIMEOUT)

            # Wait for the report properties sidebar to be available
            worker.page.wait_for_timeout(5000)

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

            # Additional wait for AngularJS to finish rendering
            worker.page.wait_for_timeout(3000)

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
