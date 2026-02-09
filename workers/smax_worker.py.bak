"""
SMAX Report Worker
==================
Generic worker for scraping SMAX report data from the SlickGrid DATA TABLE.
Add report URLs to REPORT_URLS list - the worker handles all of them the same way.

Process per report:
    1. Open the report URL
    2. Click the "Table View" button to switch from chart to grid
    3. Read column headers from SlickGrid header row
    4. Read all data rows from SlickGrid viewport
    5. Handle both text cells and checkbox/boolean cells

Performance: Opens ALL reports in parallel tabs, waits once, scrapes all at once.

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

from base_worker import BaseWorker
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
    
    # ============================================================
    # CONFIGURATION - Add your report URLs here
    # ============================================================
    REPORT_URLS = [
        "https://smax.corp.pdo.om/reports/report/69808de7e4b05f4efa3fa48f",
        "https://smax.corp.pdo.om/reports/report/6721c16be4b07e954f2bcb7e",
        "https://smax.corp.pdo.om/reports/report/60238f97e4b04b36af700a76",
        "https://smax.corp.pdo.om/reports/report/684a818ae4b07b034c72581b",
        "https://smax.corp.pdo.om/reports/report/6472f4b8e4b0636a776f1640",
        # Add more SMAX report URLs below:
        
    ]
    
    # SMAX Login Configuration (if needed)
    SMAX_BASE_URL = "https://smax.corp.pdo.om"
    SMAX_USERNAME = os.getenv('SMAX_USERNAME', '')
    SMAX_PASSWORD = os.getenv('SMAX_PASSWORD', '')
    
    # Timeout settings (milliseconds)
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
    
    def run(self) -> List[Dict[str, Any]]:
        """Execute the worker. Opens all reports in parallel tabs for speed."""
        if not self.REPORT_URLS:
            self.logger.warning("No SMAX report URLs configured.")
            return []
        
        result = []
        try:
            self.setup_browser(headless=False)
            
            if self.SMAX_USERNAME and self.SMAX_PASSWORD:
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
        tabs = []  # List of (page, url) tuples
        
        start_time = time.time()
        
        # ---- PHASE 1: Open tabs with stagger delay ----
        self.logger.info(f"Opening {len(self.REPORT_URLS)} reports in tabs (stagger={self.TAB_STAGGER_DELAY}ms)...")
        
        for i, url in enumerate(self.REPORT_URLS):
            try:
                if i == 0:
                    tab = self.page
                else:
                    tab = self.context.new_page()
                    self.page.wait_for_timeout(self.TAB_STAGGER_DELAY)
                
                tab.goto(url, wait_until='commit', timeout=self.PAGE_LOAD_TIMEOUT)
                tabs.append((tab, url))
                self.logger.info(f"  Tab {i+1}: navigation started -> {url.split('/')[-1]}")
                
            except Exception as e:
                self.logger.error(f"  Tab {i+1}: failed to open {url}: {e}")
        
        self.logger.info(f"All {len(tabs)} tabs opened in {time.time() - start_time:.1f}s")
        
        # ---- PHASE 2: Switch each tab to table view and wait for grid ----
        self.logger.info("Switching all tabs to table view...")
        
        failed_tabs = []
        
        for i, (tab, url) in enumerate(tabs):
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
                tab, url = tabs[idx]
                try:
                    self.logger.info(f"  Tab {idx+1}: reloading {url.split('/')[-1]}...")
                    tab.goto(url, wait_until='domcontentloaded', timeout=self.PAGE_LOAD_TIMEOUT)
                    self._switch_to_table_view(tab)
                    self.logger.info(f"  Tab {idx+1}: ready after retry")
                except Exception as e:
                    self.logger.warning(f"  Tab {idx+1}: retry failed: {e}")
                    still_failed.append(idx)
            
            failed_tabs = still_failed
        
        if failed_tabs:
            self.logger.warning(f"{len(failed_tabs)} tab(s) still failed: "
                                f"{[tabs[i][1].split('/')[-1] for i in failed_tabs]}")
        
        # Small buffer for final rendering
        tabs[0][0].wait_for_timeout(2000)
        
        self.logger.info(f"All tabs ready in {time.time() - start_time:.1f}s")
        
        # ---- PHASE 3: Scrape data from each tab ----
        self.logger.info("Scraping data from all tabs...")
        
        for i, (tab, url) in enumerate(tabs):
            try:
                report_data = self._extract_from_page(tab, url)
                all_results.extend(report_data)
            except Exception as e:
                self.logger.error(f"  Tab {i+1}: scrape failed for {url}: {e}")
        
        # ---- PHASE 4: Clean up extra tabs ----
        for i, (tab, url) in enumerate(tabs):
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
        if not self.SMAX_USERNAME or not self.SMAX_PASSWORD:
            return
        
        self.page.goto(f"{self.SMAX_BASE_URL}/login", wait_until='networkidle')
        
        if 'login' not in self.page.url.lower():
            self.logger.info("Already logged in to SMAX")
            return
        
        self.login_with_form(
            url=f"{self.SMAX_BASE_URL}/login",
            username=self.SMAX_USERNAME,
            password=self.SMAX_PASSWORD,
            username_selector='#username',
            password_selector='#password',
            submit_selector='button[type="submit"]',
            success_indicator='.dashboard, .main-content'
        )


# For testing the worker directly
if __name__ == '__main__':
    print("Testing SMAX Worker...")
    worker = Worker()
    results = worker.run()
    print(f"\n{len(results)} metrics scraped:")
    for r in results:
        sub = f" / {r['sub_category']}" if r.get('sub_category') else ""
        print(f"  {r['metric_title']} | {r['category']}{sub}: {r['value']}")
