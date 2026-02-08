"""
SMAX Report Worker
==================
Generic worker for scraping SMAX report data.
Add report URLs to REPORT_URLS list - the worker handles all of them the same way.

Performance: Opens ALL reports in parallel tabs, waits once, scrapes all at once.

CSV Output Format:
    Date, Source, Metric Title, Category, Value
"""

import os
import sys
import re
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_worker import BaseWorker
from typing import Dict, Any, List


class Worker(BaseWorker):
    """
    SMAX Report Scraper
    
    Extracts data from SMAX pie chart reports:
    - Report title
    - Total row count
    - All legend items with their percentage values
    
    Optimized: Opens all reports in parallel tabs for maximum speed.
    """
    
    SOURCE_NAME = "smax"
    DESCRIPTION = "SMAX Report Scraper - extracts KPIs from pie chart reports"
    
    # ============================================================
    # CONFIGURATION - Add your report URLs here
    # ============================================================
    REPORT_URLS = [
        "https://smax.corp.pdo.om/reports/report/69808de7e4b05f4efa3fa48f",
        "https://smax.corp.pdo.om/reports/report/6721c16be4b07e954f2bcb7e",
        "https://smax.corp.pdo.om/reports/report/684a818ae4b07b034c72581b",
        # Add more SMAX report URLs below:
        
    ]
    
    # SMAX Login Configuration (if needed)
    SMAX_BASE_URL = "https://smax.corp.pdo.om"
    SMAX_USERNAME = os.getenv('SMAX_USERNAME', '')
    SMAX_PASSWORD = os.getenv('SMAX_PASSWORD', '')
    
    # Timeout settings (milliseconds)
    PAGE_LOAD_TIMEOUT = 120000  # 2 minutes
    ELEMENT_WAIT_TIMEOUT = 30000
    TAB_STAGGER_DELAY = 2000    # ms delay between opening tabs (avoids server rate-limits)
    MAX_RETRIES = 2             # retry failed tabs this many times
    
    def run(self) -> List[Dict[str, Any]]:
        """
        Execute the worker. Opens all reports in parallel tabs for speed.
        """
        if not self.REPORT_URLS:
            self.logger.warning("No SMAX report URLs configured. Add URLs to REPORT_URLS list.")
            return []
        
        result = []
        try:
            self.setup_browser(headless=False)
            
            # Login if credentials are provided
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
        Scrape all SMAX reports using parallel tabs with staggered opening
        and automatic retry for failed loads.
        
        Strategy:
        1. Open tabs with a small delay between each (avoids server rate-limits)
        2. Wait for all tabs to finish loading
        3. Retry any tabs that failed (reload one at a time)
        4. Scrape data from each tab
        5. Close all extra tabs
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
                    # Small delay between opens to avoid server rate-limiting
                    self.page.wait_for_timeout(self.TAB_STAGGER_DELAY)
                
                tab.goto(url, wait_until='commit', timeout=self.PAGE_LOAD_TIMEOUT)
                tabs.append((tab, url))
                self.logger.info(f"  Tab {i+1}: navigation started -> {url.split('/')[-1]}")
                
            except Exception as e:
                self.logger.error(f"  Tab {i+1}: failed to open {url}: {e}")
        
        self.logger.info(f"All {len(tabs)} tabs opened in {time.time() - start_time:.1f}s")
        
        # ---- PHASE 2: Wait for all tabs to be ready ----
        self.logger.info("Waiting for all reports to load...")
        
        failed_tabs = []  # Indices of tabs that need retry
        
        for i, (tab, url) in enumerate(tabs):
            try:
                tab.wait_for_selector(
                    '.nv-legendtab div[data-aid="legend-item"]',
                    timeout=self.ELEMENT_WAIT_TIMEOUT
                )
                self.logger.info(f"  Tab {i+1}: ready")
            except Exception:
                self.logger.warning(f"  Tab {i+1}: not ready, queued for retry")
                failed_tabs.append(i)
        
        # ---- PHASE 2b: Retry failed tabs (sequential, one at a time) ----
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
                    tab.wait_for_selector(
                        '.nv-legendtab div[data-aid="legend-item"]',
                        timeout=self.ELEMENT_WAIT_TIMEOUT
                    )
                    self.logger.info(f"  Tab {idx+1}: ready after retry")
                except Exception as e:
                    self.logger.warning(f"  Tab {idx+1}: retry failed: {e}")
                    still_failed.append(idx)
            
            failed_tabs = still_failed
        
        if failed_tabs:
            self.logger.warning(f"{len(failed_tabs)} tab(s) still failed after all retries: {[tabs[i][1].split('/')[-1] for i in failed_tabs]}")
        
        # Small buffer for final rendering
        tabs[0][0].wait_for_timeout(2000)
        
        self.logger.info(f"All tabs loaded in {time.time() - start_time:.1f}s")
        
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
        self.logger.info(f"Scraping complete: {len(all_results)} metrics from {len(tabs)} reports in {total_time:.1f}s")
        
        return all_results
    
    def _extract_from_page(self, page, url: str) -> List[Dict[str, Any]]:
        """
        Extract all data from an already-loaded report page.
        
        Args:
            page: Playwright Page object with the loaded report
            url: The report URL (for logging)
            
        Returns:
            List of metric dictionaries
        """
        results = []
        report_id = url.split('/')[-1][:12]  # Short ID for logging
        
        # Extract Report Title
        report_title = self._get_report_title(page)
        
        # Extract Total Rows
        total_rows = self._get_total_rows(page)
        
        self.logger.info(f"  [{report_id}] {report_title}: total={total_rows}")
        
        results.append({
            'metric_title': report_title,
            'category': 'total',
            'value': total_rows
        })
        
        # Extract Legend Items
        legend_items = self._get_legend_items(page)
        for item in legend_items:
            results.append({
                'metric_title': report_title,
                'category': item['name'],
                'value': item['value']
            })
            self.logger.info(f"  [{report_id}]   {item['name']}: {item['value']}")
        
        return results
    
    # ============================================================
    # Data Extraction Helpers (accept page parameter)
    # ============================================================
    
    def _get_report_title(self, page=None) -> str:
        """Extract the report title from a page."""
        if page is None:
            page = self.page
        try:
            el = page.query_selector('xpath=/html/body/div[1]/div/div[2]/div[2]/div/div/div/div/div[1]/div/span[3]')
            if el:
                text = el.inner_text().strip()
                if text and text != 'No columns to select':
                    return text
            
            for selector in ['div.report-header span:nth-child(3)', '.report-title', 'span[data-aid="report-title"]']:
                el = page.query_selector(selector)
                if el:
                    text = el.inner_text().strip()
                    if text and text != 'No columns to select':
                        return text
            
            return "Unknown Report"
        except Exception as e:
            self.logger.warning(f"Could not get report title: {e}")
            return "Unknown Report"
    
    def _get_total_rows(self, page=None) -> int:
        """Extract the total number of rows from a page."""
        if page is None:
            page = self.page
        try:
            el = page.query_selector('xpath=/html/body/div[1]/div/div[2]/div[2]/div/div/div/div/div[1]/div/span[1]')
            if el:
                text = el.inner_text().strip()
                parsed = self._parse_number(text)
                if parsed > 0:
                    return parsed
            
            for selector in ['div.report-header span:first-child', 'span[data-aid="record-count"]', '.record-count']:
                el = page.query_selector(selector)
                if el:
                    parsed = self._parse_number(el.inner_text().strip())
                    if parsed > 0:
                        return parsed
            return 0
        except Exception as e:
            self.logger.warning(f"Could not get total rows: {e}")
            return 0
    
    def _get_legend_items(self, page=None) -> List[Dict[str, Any]]:
        """Extract all legend items (category names and values) from a page."""
        if page is None:
            page = self.page
        items = []
        try:
            legend_divs = page.query_selector_all('.nv-legendtab div[data-aid="legend-item"]')
            if not legend_divs:
                legend_divs = page.query_selector_all('.nv-legendtab > div')
            
            for div in legend_divs:
                try:
                    name_span = div.query_selector('span')
                    if not name_span:
                        continue
                    name = name_span.inner_text().strip()
                    
                    value_em = div.query_selector('em')
                    value = self._parse_percentage(value_em.inner_text().strip()) if value_em else 0.0
                    
                    items.append({'name': name, 'value': value})
                except Exception:
                    continue
        except Exception as e:
            self.logger.error(f"Error getting legend items: {e}")
        return items
    
    # ============================================================
    # Parsers
    # ============================================================
    
    def _parse_number(self, text: str) -> int:
        """Parse a number from text like '1,234 records' -> 1234"""
        try:
            numbers = re.findall(r'\d+', text.replace(',', ''))
            return int(numbers[0]) if numbers else 0
        except Exception:
            return 0
    
    def _parse_percentage(self, text: str) -> float:
        """Parse value from text like '(90.49)' -> 90.49"""
        try:
            cleaned = text.strip().strip('()').strip()
            match = re.search(r'[\d.]+', cleaned)
            return float(match.group()) if match else 0.0
        except Exception:
            return 0.0
    
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
        print(f"  {r['metric_title']} | {r['category']}: {r['value']}")
