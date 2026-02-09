"""
CUIC Report Worker
==================
Scrapes Cisco Unified Intelligence Center (CUIC) ag-grid report data.

Flow (optimised for speed):
  1. Login (2-stage: username → password + LDAP)
  2. Click Reports tab → enter reports iframe
  3. Click folder → click report (single-click, ng-grid)
  4. Filter wizard: Next → Next → Run
  5. Scrape ag-grid data → long-format dicts
"""

import os, sys, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_worker import BaseWorker
from core.config import get_worker_settings, get_worker_credentials
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

        self.url            = cfg.get('url', 'https://148.151.32.77:8444/cuicui/Main.jsp')
        self.folder_name    = cfg.get('report_folder', 'Test')
        self.report_name    = cfg.get('report_name', 'Z Call Type Historical All Fields')
        self.username       = cred.get('username', '')
        self.password       = cred.get('password', '')
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
        self.logger.info(f"Starting CUIC scraper → {self.url}")
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
        frame = self._get_reports_frame()
        if not frame:
            return []
        if not self._open_report(frame):
            return []
        if not self._run_filter_wizard():
            return []
        return self._scrape_data()

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
    def _open_report(self, frame) -> bool:
        try:
            # Click folder
            if not self._click_grid_item(frame, self.folder_name, is_folder=True):
                self.logger.error(f"Folder '{self.folder_name}' not found")
                self.screenshot("folder_not_found", is_step=False)
                return False
            self.logger.info(f"Opened folder '{self.folder_name}'")

            self.page.wait_for_timeout(self.timeout_medium)

            # Re-acquire frame if it detached
            try:
                frame.query_selector('body')
            except Exception:
                frame = self.page.frame(name=self.REPORTS_IFRAME_NAME)
                if not frame:
                    self.logger.error("Frame detached after folder click")
                    return False

            # Wait for grid to refresh
            try:
                frame.wait_for_selector(self.GRID_CONTAINER, timeout=self.timeout_nav)
            except Exception:
                self.page.wait_for_timeout(self.timeout_short)

            # Click report
            if not self._click_grid_item(frame, self.report_name, is_folder=False):
                # Try scrolling
                if not self._scroll_and_click(frame, self.report_name):
                    self.logger.error(f"Report '{self.report_name}' not found")
                    self._dump_grid(frame)
                    self.screenshot("report_not_found", is_step=False)
                    return False
            self.logger.info(f"Clicked report '{self.report_name}'")
            self.page.wait_for_timeout(self.timeout_medium)
            self.screenshot("02_report_clicked")
            return True
        except Exception as e:
            self.logger.error(f"Open report failed: {e}")
            self.screenshot("open_report_error", is_step=False)
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
    def _scrape_data(self) -> List[Dict[str, Any]]:
        try:
            self.page.wait_for_timeout(self.timeout_long)

            all_pages = self.context.pages
            target = all_pages[-1] if len(all_pages) > 1 else self.page

            for frame in target.frames:
                data = self._scrape_ag_grid(frame)
                if data:
                    self.logger.info(f"Scraped {len(data)} records from ag-grid")
                    self.screenshot("04_done")
                    return data

                data = self._scrape_html_tables(frame)
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

    def _scrape_ag_grid(self, frame) -> List[Dict[str, Any]]:
        try:
            if not frame.query_selector('.ag-root, .ag-body-viewport'):
                return []
            hdrs = [h.inner_text().strip() for h in frame.query_selector_all(
                '.ag-header-cell .ag-header-cell-text, '
                '.ag-header-cell-label .ag-header-cell-text'
            ) if h.inner_text().strip()]
            if len(hdrs) < 2:
                return []
            self.logger.info(f"ag-grid columns: {hdrs}")

            data = []
            for row in frame.query_selector_all('.ag-row'):
                vals = [c.inner_text().strip() for c in row.query_selector_all('.ag-cell')]
                if not vals or all(v == '' for v in vals):
                    continue
                cat = vals[0]
                for ci in range(1, min(len(hdrs), len(vals))):
                    data.append({
                        'metric_title': f"CUIC_{hdrs[ci]}",
                        'category': cat, 'sub_category': '', 'value': vals[ci]
                    })
            return data
        except Exception:
            return []

    def _scrape_html_tables(self, frame) -> List[Dict[str, Any]]:
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
                            'category': cat, 'sub_category': '', 'value': vals[ci]
                        })
            return data
        except Exception:
            return []
