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
from core.database import log_scrape, has_historical_data
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
            logout_ok = self._logout()
            
            if logout_ok:
                # Small delay so logout screen is visible when headless=false
                if self.page and not self.page.is_closed():
                    self.page.wait_for_timeout(1500)
            else:
                # Logout failed — keep browser open for manual intervention
                self.logger.error("")
                self.logger.error("="*60)
                self.logger.error("⚠⚠⚠ KEEPING BROWSER OPEN FOR 60 SECONDS ⚠⚠⚠")
                self.logger.error("Please manually logout:")
                self.logger.error("1. Click the user menu (top right)")
                self.logger.error("2. Click 'Sign Out'")
                self.logger.error("Or visit: https://148.151.32.77:8444/cuicui/Logout.jsp")
                self.logger.error("="*60)
                if self.page and not self.page.is_closed():
                    self.page.wait_for_timeout(60000)  # 60 seconds
            
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

            # Skip historical reports that already have data
            if report.get('data_type') == 'historical':
                if has_historical_data('cuic', label):
                    self.logger.info(f"Report '{label}': HISTORICAL — already scraped, skipping")
                    log_scrape('cuic', label, 'skipped', 0, 0, 'Historical data already exists')
                    continue

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
    def _logout(self) -> bool:
        """Sign out of CUIC so the session is released.
        Logout UI lives in the MAIN page (outside any iframe).

        Strategy: Multiple selectors (ID, class, XPath)
          1. Click user menu button (tries multiple selectors)
          2. Click sign-out link (tries multiple selectors)
          → Navigates to Logout.jsp
        
        Returns: True if logout succeeded, False if manual logout required
        """
        try:
            if not self.context:
                self.logger.warning("⚠ No browser context – skipping logout")
                return False

            # Always use the FIRST page (main CUIC tab) for logout
            pages = self.context.pages
            if not pages:
                self.logger.warning("⚠ No pages open – skipping logout")
                return False

            # Close all extra tabs/popups first
            self.logger.info("Closing extra browser tabs...")
            while len(pages) > 1:
                try:
                    pages[-1].close()
                    self.logger.info(f"  Closed tab — {len(pages)-1} remaining")
                except Exception:
                    pass
                pages = self.context.pages

            main_page = pages[0]
            if main_page.is_closed():
                self.logger.warning("⚠ Main page already closed – skipping logout")
                return False

            self.logger.info("="*60)
            self.logger.info("LOGOUT SEQUENCE STARTING")
            self.logger.info("="*60)

            # Dismiss any open dialogs/modals by pressing Escape
            self.logger.info("Pressing Escape to dismiss any modals...")
            try:
                main_page.keyboard.press('Escape')
                main_page.wait_for_timeout(500)
                main_page.keyboard.press('Escape')
                main_page.wait_for_timeout(500)
            except Exception:
                pass

            # Screenshot before logout
            try:
                main_page.screenshot(path=f"{self.log_dir}/logout_01_before.png")
                self.logger.info("📸 Screenshot: logout_01_before.png")
            except Exception:
                pass

            logged_out = False

            # ── XPath/CSS multi-strategy clicks ──────────────────────────
            try:
                # IMPORTANT: User menu button is inside remote_iframe_0 iframe!
                self.logger.info("STEP 1: Locating identity_gadget iframe...")
                
                identity_frame = main_page.frame(name='remote_iframe_0')
                if not identity_frame:
                    self.logger.error("  ✗ Could not find remote_iframe_0")
                    try:
                        main_page.screenshot(path=f"{self.log_dir}/logout_iframe_not_found.png")
                        self.logger.info("📸 Screenshot: logout_iframe_not_found.png")
                    except Exception:
                        pass
                    return False
                
                self.logger.info("  ✓ Found iframe: remote_iframe_0")

                # Try specific selectors for the user menu button INSIDE the iframe
                # Start with most specific, fall back to generic
                user_menu_selectors = [
                    'div[id*="user"]',                         # Div with 'user' in ID
                    'button[id*="user"]',                      # Button with 'user' in ID
                    'a[id*="user"]',                           # Link with 'user' in ID
                    'div.user-info',                           # Class-based
                    'button:visible',                          # Any visible button (fallback)
                    'a:visible',                               # Any visible link (fallback)
                    'div:visible',                             # Any visible div (last resort)
                ]
                
                self.logger.info("STEP 2: Clicking user menu button (inside iframe)...")
                menu_clicked = False
                
                for selector in user_menu_selectors:
                    try:
                        self.logger.info(f"  Trying: {selector}")
                        user_menu = identity_frame.locator(selector)
                        menu_count = user_menu.count()
                        
                        if menu_count > 0:
                            self.logger.info(f"    Found {menu_count} element(s)")
                            user_menu.first.wait_for(state='visible', timeout=5000)
                            user_menu.first.click(force=True)
                            self.logger.info(f"  ✓ Clicked user menu")
                            menu_clicked = True
                            break
                    except Exception as e:
                        self.logger.debug(f"    Failed: {e}")
                        continue
                
                if not menu_clicked:
                    self.logger.error("  ✗ All user menu selectors failed (tried inside iframe)")
                    try:
                        main_page.screenshot(path=f"{self.log_dir}/logout_menu_not_found.png")
                        self.logger.info("📸 Screenshot: logout_menu_not_found.png")
                    except Exception:
                        pass
                    return False
                
                # Wait for dropdown menu to appear (more reliable than fixed timeout)
                self.logger.info("STEP 3: Waiting for dropdown menu...")
                try:
                    main_page.locator('ul#id-gt-ul').wait_for(state='visible', timeout=3000)
                    self.logger.info("  ✓ Dropdown menu visible")
                except Exception:
                    self.logger.warning("  ⚠ Dropdown didn't appear, trying anyway...")
                    main_page.wait_for_timeout(1500)
                
                # Screenshot after menu click
                try:
                    main_page.screenshot(path=f"{self.log_dir}/logout_02_menu_opened.png")
                    self.logger.info("📸 Screenshot: logout_02_menu_opened.png")
                except Exception:
                    pass

                # STEP 4: Click sign-out link (in MAIN page, not iframe)
                # The dropdown menu appears in the main page after clicking the iframe button
                signout_selectors = [
                    '#so_anchor',                          # Most reliable - direct ID of <a>
                    '#signout-btn1 a',                     # ID of <li> + descendant <a>
                    'a:has-text("Sign Out")',             # Text match
                    'ul#id-gt-ul a:has-text("Sign Out")', # Full path with text
                    'xpath=//a[@id="so_anchor"]',         # XPath for anchor
                    'xpath=//li[@id="signout-btn1"]/a',   # XPath with ID
                ]
                
                self.logger.info("STEP 4: Clicking sign-out link (in main page)...")
                
                for selector in signout_selectors:
                    try:
                        self.logger.info(f"  Trying: {selector}")
                        signout_link = main_page.locator(selector)
                        signout_count = signout_link.count()
                        
                        if signout_count > 0:
                            self.logger.info(f"    Found {signout_count} element(s)")
                            signout_link.first.wait_for(state='visible', timeout=5000)
                            signout_link.first.click(force=True)
                            self.logger.info(f"  ✓ Clicked sign-out")
                            
                            # Wait for navigation to Logout.jsp
                            try:
                                main_page.wait_for_url('**/Logout.jsp**', timeout=5000)
                                self.logger.info("  ✓ Navigated to Logout.jsp")
                            except Exception:
                                main_page.wait_for_timeout(3000)  # Fallback to fixed wait
                            
                            logged_out = True
                            break
                    except Exception as e:
                        self.logger.debug(f"    Failed: {e}")
                        continue
                
                if not logged_out:
                    self.logger.error("  ✗ All sign-out selectors failed")
                    # Try to take a screenshot to see what's on screen
                    try:
                        main_page.screenshot(path=f"{self.log_dir}/logout_signout_not_found.png")
                        self.logger.info("📸 Screenshot: logout_signout_not_found.png")
                    except Exception:
                        pass
                    
            except Exception as e:
                self.logger.error(f"✗ Logout click sequence failed: {e}")

            # Screenshot final state
            try:
                main_page.screenshot(path=f"{self.log_dir}/logout_03_complete.png")
                self.logger.info("📸 Screenshot: logout_03_complete.png")
            except Exception:
                pass

            # ── Verification ─────────────────────────────────────────────
            main_page.wait_for_timeout(2000)
            try:
                final_url = main_page.url
                is_logout_page = 'logout' in final_url.lower()
                
                if logged_out and is_logout_page:
                    self.logger.info("="*60)
                    self.logger.info(f"✓✓✓ LOGOUT SUCCESSFUL ✓✓✓")
                    self.logger.info(f"Final URL: {final_url}")
                    self.logger.info("="*60)
                elif logged_out:
                    self.logger.warning("="*60)
                    self.logger.warning(f"⚠ Logout clicks completed but NOT on logout page")
                    self.logger.warning(f"Final URL: {final_url}")
                    self.logger.warning("="*60)
                else:
                    self.logger.error("="*60)
                    self.logger.error("✗✗✗ LOGOUT FAILED — MANUAL LOGOUT REQUIRED ✗✗✗")
                    self.logger.error(f"Final URL: {final_url}")
                    self.logger.error("To prevent session limit, manually visit:")
                    self.logger.error("https://148.151.32.77:8444/cuicui/Logout.jsp")
                    self.logger.error("="*60)
            except Exception:
                pass
            
            return logged_out

        except Exception as e:
            self.logger.error("="*60)
            self.logger.error(f"✗✗✗ LOGOUT EXCEPTION: {e}")
            self.logger.error("MANUAL LOGOUT REQUIRED to prevent session limit!")
            self.logger.error("="*60)
            try:
                if self.context and self.context.pages:
                    self.context.pages[0].screenshot(path=f"{self.log_dir}/logout_error.png")
            except Exception:
                pass
            return False

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

            # Defensive: remove report name from folder segments if it slipped in
            if folders and report_name and folders[-1] == report_name:
                self.logger.warning(f"Report name '{report_name}' found in folder path — removing duplicate")
                folders = folders[:-1]

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

    # ── Multi-step wizard reader ─────────────────────────────────────────
    # CUIC multi-step wizards use <filter-wizard> with wizardConfig.steps.
    # Each step has its own Angular controller (HCFFilterCtrl for datetime,
    # cuic-filter for valuelists, individual-filters for field filters).
    # This JS reads the CURRENT visible step's data via Angular scopes.
    CUIC_MULTISTEP_READ_JS = r'''() => {
        if (typeof angular === 'undefined') return {_debug: 'no_angular'};

        /* ── locate the filter-wizard element ── */
        const wizEl = document.querySelector('filter-wizard');
        if (!wizEl) return {_debug: 'no_filter_wizard_element',
            hasModal: !!document.querySelector('.modal-dialog'),
            hasRunReport: !!document.querySelector('run-report-filter'),
            bodyClasses: document.body.className.substring(0, 200)};
        let wizScope;
        try { wizScope = angular.element(wizEl).scope(); } catch(e) {
            return {_debug: 'scope_error', error: e.message};
        }
        if (!wizScope) return {_debug: 'no_scope_on_wizard'};

        /* Enhanced debug info collection */
        const debugInfo = {
            scopeKeys: Object.keys(wizScope).filter(k => !k.startsWith('$')).slice(0,30),
            allScopeKeys: Object.keys(wizScope).slice(0,30),
            parentKeys: wizScope.$parent ? Object.keys(wizScope.$parent).filter(k => !k.startsWith('$')).slice(0,30) : [],
            grandparentKeys: wizScope.$parent?.$parent ? Object.keys(wizScope.$parent.$parent).filter(k => !k.startsWith('$')).slice(0,30) : [],
        };
        
        /* Try isolateScope instead of regular scope */
        let isoScope = null;
        try {
            isoScope = angular.element(wizEl).isolateScope();
            if (isoScope) {
                debugInfo.hasIsolateScope = true;
                debugInfo.isoScopeKeys = Object.keys(isoScope).filter(k => !k.startsWith('$')).slice(0,30);
            }
        } catch(e) {}
        
        /* Walk up to find wizardConfig - check nested objects and parent chain */
        let wc = wizScope.wizardConfig 
              || isoScope?.wizardConfig
              || wizScope.runReportFilterForm?.wizardConfig
              || wizScope.ctrl?.wizardConfig
              || wizScope.vm?.wizardConfig
              || wizScope.$parent?.wizardConfig
              || wizScope.$parent?.$parent?.wizardConfig
              || wizScope.$parent?.$parent?.$parent?.wizardConfig;
        
        /* If still not found, try the controller directly with various names */
        if (!wc) {
            const ctrlNames = ['filterWizard', 'FilterWizardCtrl', 'wizardCtrl', 'runReportFilter'];
            for (const name of ctrlNames) {
                try {
                    const ctrl = angular.element(wizEl).controller(name);
                    if (ctrl) {
                        debugInfo.foundController = name;
                        debugInfo.ctrlKeys = Object.keys(ctrl).slice(0,30);
                        wc = ctrl.wizardConfig || ctrl.config || ctrl.steps;
                        if (wc) break;
                    }
                } catch(e) {}
            }
        }
        
        /* Try to find steps directly on various scopes */
        if (!wc && !wc?.steps) {
            const stepsCheck = wizScope.steps || isoScope?.steps || wizScope.$parent?.steps;
            if (stepsCheck && Array.isArray(stepsCheck) && stepsCheck.length >= 2) {
                wc = {steps: stepsCheck};
                debugInfo.foundStepsDirectly = true;
            }
        }
        
        if (!wc) return {_debug: 'no_wizardConfig', ...debugInfo};
        if (!wc.steps || wc.steps.length < 2) return {_debug: 'not_multistep', stepsCount: wc.steps?.length || 0};

        /* Read step tabs (titles) */
        const stepTitles = wc.steps.map(s => s.title || s.wzTitle || '');

        /* Read the CURRENTLY VISIBLE step's filters */
        const sections = document.querySelectorAll('filter-wizard .steps > section');
        let currentIdx = -1;
        sections.forEach((sec, i) => {
            if (sec.style.display !== 'none') currentIdx = i;
        });
        if (currentIdx < 0) return null;

        const sec = sections[currentIdx];
        const stepTitle = stepTitles[currentIdx] || ('Step ' + (currentIdx+1));

        /* Detect what kind of filter is in this step */
        const result = {
            type: 'cuic_multistep',
            stepIndex: currentIdx,
            stepTitle: stepTitle,
            stepCount: wc.steps.length,
            stepTitles: stepTitles,
            params: []
        };

        /* ── DATETIME filter (HCFFilterCtrl / datetime-filter) ── */
        const dtFilter = sec.querySelector('datetime-filter');
        if (dtFilter) {
            let dtScope;
            try { dtScope = angular.element(dtFilter).scope(); } catch(e) {}
            if (dtScope) {
                /* Read the heading text for label */
                const heading = sec.querySelector('.accordion--navigation a');
                const label = heading ? heading.textContent.replace(/[^a-zA-Z0-9_ ()]/g,'').trim() : 'DateTime';

                /* Date preset options */
                const datePresets = [];
                const selEl = dtFilter.querySelector('.csSelect-container');
                if (selEl) {
                    try {
                        const selScope = angular.element(selEl).scope();
                        const opts = selScope?.csSelect?.options || selScope?.sel?.options || [];
                        opts.forEach(o => datePresets.push({
                            value: o.value || o.id || '',
                            label: o.label || o.name || o.value || ''
                        }));
                    } catch(e) {}
                }
                /* If no options found from scope, try DOM */
                if (datePresets.length === 0) {
                    dtFilter.querySelectorAll('.select-options li a').forEach(a => {
                        datePresets.push({value: a.title || a.textContent.trim(),
                                         label: a.textContent.trim()});
                    });
                }

                /* Current preset from selected display */
                const selText = dtFilter.querySelector('.select-toggle');
                let currentPreset = selText ? selText.textContent.trim() : '';
                const matched = datePresets.find(p => p.label === currentPreset);
                if (matched) currentPreset = matched.value;

                /* Detect filterType from scope */
                const dtField = dtScope.dateTimeField || dtScope.hcfCtrl?.historicalFilterField || {};
                const filterType = dtField.filterType || 'DATETIME';
                const hasTimeRange = filterType === 'DATETIME';

                result.params.push({
                    dataType: filterType,
                    type: 'cuic_datetime',
                    label: label,
                    paramName: label,
                    datePresets: datePresets,
                    currentPreset: currentPreset,
                    hasDateRange: true,
                    hasTimeRange: hasTimeRange,
                    isRequired: true
                });
            }
        }

        /* ── VALUELIST filter (cuic-filter / cuic-switcher) ── */
        const vlFilter = sec.querySelector('[ng-switch-when="VALUELIST"]');
        if (vlFilter) {
            const heading = sec.querySelector('.accordion--navigation a');
            const rawLabel = heading ? heading.textContent.trim() : 'Values';
            /* Extract label and paramName: "Call Types(CallTypeID)" → label="Call Types", paramName="CallTypeID" */
            const labelMatch = rawLabel.match(/^(.+?)\s*\(([^)]+)\)\s*$/);
            const label = labelMatch ? labelMatch[1].trim() : rawLabel;
            const paramName = labelMatch ? labelMatch[2].trim() : rawLabel;

            const leftPane = vlFilter.querySelector('[cuic-pane="left"]');
            const rightPane = vlFilter.querySelector('[cuic-pane="right"]');
            const switcherEl = vlFilter.querySelector('[cuic-switcher]');
            const allNames = [];
            const groups = [];
            const selectedNames = [];
            let _vlDebug = {};

            /* Helper: flatten a model array into allNames / groups */
            function collectFromModel(list, targetNames, targetGroups) {
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
                        if (targetGroups) {
                            targetGroups.push({name: v.name || '',
                                             count: v.totalElements || v.children.length,
                                             members: memberNames});
                        }
                        memberNames.forEach(n => { if (!targetNames.includes(n)) targetNames.push(n); });
                    } else {
                        const n = v.name || '';
                        if (n && !targetNames.includes(n)) targetNames.push(n);
                    }
                });
            }

            /*
             * PRIMARY: Use isolateScope() on cuic-switcher or cuic-pane.
             * cuic-switcher directive binds: left-model → leftModel, right-model → rightModel
             * cuic-pane directive binds: model → model
             * isolateScope() returns the directive's OWN scope (not the vs-repeat child scope).
             * This bypasses virtual scrolling entirely.
             */

            /* Try cuic-switcher isolateScope first (has BOTH left and right models) */
            if (switcherEl) {
                try {
                    const swIso = angular.element(switcherEl).isolateScope();
                    if (swIso) {
                        _vlDebug.switcherIsoKeys = Object.keys(swIso).filter(k => !k.startsWith('$')).slice(0,30);
                        /* leftModel = full available list */
                        if (Array.isArray(swIso.leftModel) && swIso.leftModel.length > 0) {
                            collectFromModel(swIso.leftModel, allNames, groups);
                            _vlDebug.source = 'switcher.isolateScope.leftModel';
                            _vlDebug.rawCount = swIso.leftModel.length;
                        }
                        /* rightModel = full selected list */
                        if (Array.isArray(swIso.rightModel) && swIso.rightModel.length > 0) {
                            collectFromModel(swIso.rightModel, selectedNames, null);
                            _vlDebug.selectedSource = 'switcher.isolateScope.rightModel';
                        }
                    }
                } catch(e) { _vlDebug.switcherIsoErr = e.message; }
            }

            /* Fallback: cuic-pane isolateScope for available values */
            if (leftPane && allNames.length === 0) {
                try {
                    const lpIso = angular.element(leftPane).isolateScope();
                    if (lpIso) {
                        _vlDebug.paneIsoKeys = Object.keys(lpIso).filter(k => !k.startsWith('$')).slice(0,30);
                        if (Array.isArray(lpIso.model) && lpIso.model.length > 0) {
                            collectFromModel(lpIso.model, allNames, groups);
                            _vlDebug.source = 'pane.isolateScope.model';
                            _vlDebug.rawCount = lpIso.model.length;
                        }
                    }
                } catch(e) { _vlDebug.paneIsoErr = e.message; }
            }

            /* Fallback: walk scope chain to find item.lvaluelist */
            if (allNames.length === 0 && (switcherEl || leftPane)) {
                try {
                    let s = angular.element(switcherEl || leftPane).scope();
                    for (let depth = 0; s && depth < 10; depth++, s = s.$parent) {
                        if (s.item && Array.isArray(s.item.lvaluelist) && s.item.lvaluelist.length > 0) {
                            collectFromModel(s.item.lvaluelist, allNames, groups);
                            _vlDebug.source = 'scope.item.lvaluelist@depth' + depth;
                            _vlDebug.rawCount = s.item.lvaluelist.length;
                            break;
                        }
                    }
                } catch(e) { _vlDebug.scopeWalkErr = e.message; }
            }

            /* Fallback: cuic-pane isolateScope for selected values */
            if (rightPane && selectedNames.length === 0) {
                try {
                    const rpIso = angular.element(rightPane).isolateScope();
                    if (rpIso && Array.isArray(rpIso.model) && rpIso.model.length > 0) {
                        collectFromModel(rpIso.model, selectedNames, null);
                        _vlDebug.selectedSource = 'pane.right.isolateScope.model';
                    }
                } catch(e) {}
            }

            /* Fallback: scope chain for item.rvaluelist (selected values) */
            if (selectedNames.length === 0 && (switcherEl || rightPane)) {
                try {
                    let s = angular.element(switcherEl || rightPane).scope();
                    for (let depth = 0; s && depth < 10; depth++, s = s.$parent) {
                        if (s.item && Array.isArray(s.item.rvaluelist) && s.item.rvaluelist.length > 0) {
                            collectFromModel(s.item.rvaluelist, selectedNames, null);
                            _vlDebug.selectedSource = 'scope.item.rvaluelist@depth' + depth;
                            break;
                        }
                    }
                } catch(e) {}
            }

            /* Last resort: read what's visible in DOM (partial, only rendered items) */
            if (leftPane && allNames.length === 0) {
                leftPane.querySelectorAll('.cuic-switcher-name').forEach(el => {
                    const name = (el.title || el.textContent || '').trim();
                    if (name && !allNames.includes(name)) allNames.push(name);
                });
                _vlDebug.source = 'dom_fallback';
                _vlDebug.partial = true;
            }
            if (rightPane && selectedNames.length === 0) {
                rightPane.querySelectorAll('.cuic-switcher-name').forEach(el => {
                    const name = (el.title || el.textContent || '').trim();
                    if (name && !selectedNames.includes(name)) selectedNames.push(name);
                });
            }

            /* Read the "Available: N Values" text to get total expected count */
            let totalAvailable = allNames.length;
            const totalLabel = (leftPane || vlFilter).querySelector('.cuic-switcher-total-label .ng-binding');
            if (totalLabel) {
                const m = totalLabel.textContent.match(/(\d+)\s*Values?/i);
                if (m) totalAvailable = parseInt(m[1], 10);
            }

            result.params.push({
                dataType: 'VALUELIST',
                type: 'cuic_valuelist',
                label: label,
                paramName: paramName,
                isRequired: true,
                totalAvailable: totalAvailable,
                availableCount: allNames.length,
                availableNames: allNames,
                availableGroups: groups,
                selectedCount: selectedNames.length,
                selectedValues: selectedNames,
                _vlDebug: _vlDebug,
                _needsScroll: allNames.length < totalAvailable
            });
        }

        /* ── Individual Field Filters (step 3 type) ── */
        const iffFields = sec.querySelector('#cuic-iff-fields');
        if (iffFields) {
            const availableFields = [];
            iffFields.querySelectorAll('.select-options li a').forEach(a => {
                const txt = (a.title || a.textContent || '').trim();
                const m = txt.match(/^(.+?)\s*\(([^)]+)\)\s*$/);
                availableFields.push({
                    label: m ? m[1].trim() : txt,
                    fieldId: m ? m[2].trim() : txt,
                    combined: txt
                });
            });

            /* Capture already-selected fields from the Angular vm.selectedList */
            let selectedFieldIds = [];
            try {
                const iffScope = angular.element(iffFields).scope();
                if (iffScope && iffScope.vm && iffScope.vm.selectedList) {
                    selectedFieldIds = iffScope.vm.selectedList.map(f => {
                        const cn = (f.combinedName || '').trim();
                        const pm = cn.match(/^(.+?)\s*\(([^)]+)\)\s*$/);
                        return pm ? pm[2].trim() : (f.id || f.name || f.fieldName || cn);
                    });
                }
            } catch(e) {}

            result.params.push({
                dataType: 'FIELD_FILTER',
                type: 'cuic_field_filter',
                label: 'Field Filters',
                paramName: '_field_filters',
                availableFields: availableFields,
                selectedFieldIds: selectedFieldIds
            });
        }

        return result.params.length > 0 ? result : null;
    }'''  # noqa: E501

    # ── SPAB (single-step) wizard reader ─────────────────────────────────
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
        """Read wizard fields. Tries CUIC multi-step first, then SPAB, then generic.
        Returns dict with 'type' key: 'cuic_multistep', 'cuic_spab', or 'generic'."""
        
        # ── Debug: check what's on the page ──
        for f in self.page.frames:
            try:
                diag = f.evaluate(r'''() => {
                    return {
                        hasAngular: typeof angular !== 'undefined',
                        hasFilterWizard: !!document.querySelector('filter-wizard'),
                        hasSpabCtrl: !!document.querySelector('[ng-controller*="spab"]'),
                        visibleSections: document.querySelectorAll('filter-wizard .steps > section').length,
                        hasModalDialog: !!document.querySelector('.modal-dialog'),
                        url: window.location.href
                    };
                }''')
                self.logger.info(f"  Page diagnostic: {diag}")
            except Exception as e:
                self.logger.debug(f"  Diagnostic failed: {e}")
        
        # ── CUIC multi-step wizard (filter-wizard with wizardConfig.steps) ──
        for f in self.page.frames:
            try:
                result = f.evaluate(self.CUIC_MULTISTEP_READ_JS)
                if result and result.get('_debug'):
                    self.logger.info(f"  Multi-step reader debug ({f.url[:60]}): {result}")
                    continue
                if result and result.get('type') == 'cuic_multistep':
                    self.logger.info(f"  ✓ CUIC multi-step wizard step {result.get('stepIndex',0)+1}: "
                                     f"{len(result.get('params',[]))} param(s)")

                    # ── Async scroll fallback for valuelist ──
                    # If isolateScope didn't return full data, scroll the
                    # virtual list in the browser to collect all items.
                    for p in result.get('params', []):
                        if p.get('type') == 'cuic_valuelist' and p.get('_needsScroll'):
                            self.logger.info(
                                f"  Valuelist '{p['label']}' needs scroll: "
                                f"{p['availableCount']}/{p['totalAvailable']}")
                            self._scroll_collect_valuelist(f, p)

                    return result
            except Exception as e:
                self.logger.warning(f"  Multi-step reader exception ({f.url[:60]}): {e}")
                pass

        # ── CUIC SPAB (single-step) path ──
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

    # ── Async scroll-based valuelist collection ──────────────────────────
    def _scroll_collect_valuelist(self, frame, param: dict):
        """Scroll the virtual-scrolled valuelist in the browser to collect
        all items when isolateScope() didn't return the full dataset.

        Mutates *param* in-place: updates availableNames, availableCount,
        and clears _needsScroll.
        """
        total_expected = param.get('totalAvailable', 0)
        collected = set(param.get('availableNames', []))

        # JS to read currently visible items + scroll info
        SCROLL_READ_JS = r'''(pane) => {
            const container = document.querySelector(
                '[ng-switch-when="VALUELIST"] [cuic-pane="' + pane + '"] .cuic-switcher-list'
            );
            if (!container) return null;
            const names = [];
            container.querySelectorAll('.cuic-switcher-name').forEach(el => {
                const n = (el.title || el.textContent || '').trim();
                if (n) names.push(n);
            });
            return {
                names: names,
                scrollTop: container.scrollTop,
                scrollHeight: container.scrollHeight,
                clientHeight: container.clientHeight
            };
        }'''

        SCROLL_SET_JS = r'''(pos) => {
            const container = document.querySelector(
                '[ng-switch-when="VALUELIST"] [cuic-pane="left"] .cuic-switcher-list'
            );
            if (container) container.scrollTop = pos;
        }'''

        try:
            max_iterations = 50
            for i in range(max_iterations):
                info = frame.evaluate(SCROLL_READ_JS, 'left')
                if not info:
                    break

                for n in info.get('names', []):
                    collected.add(n)

                self.logger.debug(
                    f"    Scroll iter {i}: collected={len(collected)}/{total_expected} "
                    f"scrollTop={info['scrollTop']}/{info['scrollHeight']}")

                if len(collected) >= total_expected:
                    break

                # Scroll down by one viewport
                new_pos = info['scrollTop'] + info['clientHeight']
                if new_pos >= info['scrollHeight']:
                    break

                frame.evaluate(SCROLL_SET_JS, new_pos)
                self.page.wait_for_timeout(150)  # let Angular digest

            # Update param in-place
            param['availableNames'] = sorted(collected)
            param['availableCount'] = len(collected)
            param['_needsScroll'] = False
            self.logger.info(
                f"  After scrolling: {len(collected)}/{total_expected} valuelist items collected")

        except Exception as e:
            self.logger.warning(f"  Scroll collection failed: {e}")

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

        stype = step_info.get('type', '')

        if stype == 'cuic_spab':
            # ── CUIC SPAB: apply via Angular scope ──
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

        elif stype == 'cuic_multistep':
            # ── CUIC multi-step: apply to current visible step ──
            # saved_values are keyed by paramName within this step
            params = step_info.get('params', [])
            for p in params:
                pn = p.get('paramName', '')
                val = saved_values.get(pn)
                if val is None:
                    continue

                if p.get('type') == 'cuic_datetime':
                    # Apply datetime preset via Angular scope on datetime-filter element
                    cfg = {'preset': val} if isinstance(val, str) else (val or {})
                    applied = False
                    for f in self.page.frames:
                        try:
                            result = f.evaluate(r'''(cfg) => {
                                if (typeof angular === 'undefined') return {error: 'no_angular'};
                                const dtFilter = document.querySelector(
                                    'filter-wizard .steps > section[style*="display: flex"] datetime-filter'
                                );
                                if (!dtFilter) return {error: 'no_datetime_filter_element'};

                                // Try isolateScope first, then regular scope
                                let scope = null;
                                try { scope = angular.element(dtFilter).isolateScope(); } catch(e) {}
                                if (!scope) {
                                    try { scope = angular.element(dtFilter).scope(); } catch(e) {}
                                }
                                if (!scope) return {error: 'no_scope'};

                                const preset = cfg.preset || null;
                                if (!preset) return {error: 'no_preset_in_cfg'};

                                // Find the csSelect options — walk scope chain to find sel/csSelect
                                let opts = [];
                                const selContainer = dtFilter.querySelector('.csSelect-container');
                                if (selContainer) {
                                    try {
                                        let selScope = angular.element(selContainer).isolateScope()
                                                    || angular.element(selContainer).scope();
                                        opts = selScope?.csSelect?.options || selScope?.sel?.options || [];
                                    } catch(e) {}
                                }
                                // Fallback: walk up from datetime-filter scope
                                if (!opts.length) {
                                    opts = scope.sel?.options || scope.csSelect?.options || [];
                                    let s = scope;
                                    for (let d = 0; !opts.length && s && d < 5; d++, s = s.$parent) {
                                        opts = s.sel?.options || s.csSelect?.options || [];
                                    }
                                }
                                if (!opts.length) return {error: 'no_options_found', scopeKeys: Object.keys(scope).filter(k=>!k.startsWith('$')).slice(0,20)};

                                const opt = opts.find(o => o.value === preset);
                                if (!opt) return {error: 'preset_not_found', preset: preset, available: opts.map(o=>o.value)};

                                // Apply the selected preset
                                scope.relativeRangeSelected = opt;
                                if (scope.updateRDChange) scope.updateRDChange(0);
                                else if (scope.onRelativeRangeChange) scope.onRelativeRangeChange();
                                try { scope.$apply(); } catch(e) {}
                                return {ok: true, value: preset};
                            }''', cfg)
                            if result and result.get('ok'):
                                self.logger.info(f"    {pn}: OK → {result.get('value','')}")
                                applied = True
                                break
                            elif result and result.get('error'):
                                self.logger.debug(f"    {pn}: datetime frame skip: {result}")
                        except Exception as e:
                            self.logger.debug(f"    {pn}: datetime frame error: {e}")
                    if not applied:
                        self.logger.warning(f"    {pn}: datetime preset '{cfg.get('preset','')}' could NOT be applied")

                elif p.get('type') == 'cuic_valuelist':
                    # Apply valuelist via cuic-switcher isolateScope
                    # MUST: (1) clear existing right pane, (2) move only desired items to right
                    applied = False
                    for f in self.page.frames:
                        try:
                            result = f.evaluate(r'''(cfg) => {
                                if (typeof angular === 'undefined') return {error: 'no_angular'};
                                const section = document.querySelector(
                                    'filter-wizard .steps > section[style*="display: flex"]'
                                );
                                if (!section) return {error: 'no_visible_section'};
                                const switcher = section.querySelector('[cuic-switcher]');
                                if (!switcher) return {error: 'no_cuic_switcher'};

                                // MUST use isolateScope to get the directive's own scope
                                let scope = null;
                                try { scope = angular.element(switcher).isolateScope(); } catch(e) {}
                                if (!scope) {
                                    try { scope = angular.element(switcher).scope(); } catch(e) {}
                                }
                                if (!scope) return {error: 'no_scope_on_switcher'};

                                const leftModel = scope.leftModel;
                                const rightModel = scope.rightModel;
                                if (!leftModel || !rightModel)
                                    return {error: 'no_leftModel_or_rightModel',
                                            keys: Object.keys(scope).filter(k=>!k.startsWith('$')).slice(0,20)};

                                // Helper: flatten grouped items
                                function flattenAll(list) {
                                    const out = [];
                                    (list||[]).forEach(v => {
                                        if (v.children && v.children.length)
                                            out.push(...flattenAll(v.children));
                                        else out.push(v);
                                    });
                                    return out;
                                }

                                // Step 1: Move ALL existing right items back to left first
                                const existingRight = flattenAll(rightModel);
                                if (existingRight.length > 0) {
                                    leftModel.push(...existingRight);
                                    rightModel.length = 0;
                                }

                                if (cfg.value === 'all') {
                                    // Move everything to right
                                    const all = flattenAll(leftModel);
                                    rightModel.push(...all);
                                    leftModel.length = 0;
                                    try { scope.$apply(); } catch(e) {}
                                    return {ok: true, value: 'all', count: rightModel.length};

                                } else if (Array.isArray(cfg.value)) {
                                    // Move only the specified items to right
                                    const names = new Set(cfg.value);
                                    const allFlat = flattenAll(leftModel);
                                    const toRight = [], toLeft = [];
                                    allFlat.forEach(v => {
                                        if (names.has(v.name)) toRight.push(v);
                                        else toLeft.push(v);
                                    });
                                    leftModel.length = 0;
                                    toLeft.forEach(v => leftModel.push(v));
                                    toRight.forEach(v => rightModel.push(v));
                                    try { scope.$apply(); } catch(e) {}
                                    return {ok: true, value: toRight.map(v=>v.name),
                                            wanted: cfg.value.length, got: toRight.length};
                                }
                                return {error: 'invalid_value_type'};
                            }''', {'value': val})
                            if result and result.get('ok'):
                                self.logger.info(f"    {pn}: OK → {result.get('value','')}")
                                if isinstance(result.get('value'), list):
                                    wanted = result.get('wanted', 0)
                                    got = result.get('got', 0)
                                    if got < wanted:
                                        self.logger.warning(f"    {pn}: only {got}/{wanted} items found in available list")
                                applied = True
                                break
                            elif result and result.get('error'):
                                self.logger.debug(f"    {pn}: valuelist frame skip: {result}")
                        except Exception as e:
                            self.logger.debug(f"    {pn}: valuelist frame error: {e}")
                    if not applied:
                        self.logger.warning(f"    {pn}: valuelist could NOT be applied (val={val})")

                elif p.get('type') == 'cuic_field_filter':
                    # Apply field filters — select fields from dropdown and configure criteria
                    # val is a list of: ["field_id"] OR [{"id": "field_id", "operator": "EQ", "value1": "10"}]
                    if val == 'all' or not val:
                        self.logger.info(f"    {pn}: field_filter = {'all (no filtering)' if val == 'all' else 'none'}")
                        continue
                    if not isinstance(val, list):
                        continue
                    
                    # Map settings UI operator codes → CUIC internal operator codes
                    _op_map = {
                        'EQ': 'EQ', 'NE': 'NEQ', 'NEQ': 'NEQ',
                        'GT': 'G', 'G': 'G',
                        'GE': 'GEQ', 'GEQ': 'GEQ',
                        'LT': 'L', 'L': 'L',
                        'LE': 'LEQ', 'LEQ': 'LEQ',
                        'BW': 'BTWN', 'BTWN': 'BTWN',
                        'CT': 'CT',
                    }

                    # Normalize to object format
                    normalized = []
                    for item in val:
                        if isinstance(item, str):
                            normalized.append({"id": item})
                        elif isinstance(item, dict):
                            cfg = dict(item)
                            if cfg.get('operator'):
                                cfg['operator'] = _op_map.get(cfg['operator'], cfg['operator'])
                            normalized.append(cfg)
                    
                    self.logger.info(f"    {pn}: field_filter applying {len(normalized)} field(s)...")

                    # ── Phase 1: First remove any existing field filters ──
                    try:
                        for f in self.page.frames:
                            try:
                                clear_result = f.evaluate(r'''() => {
                                    if (typeof angular === 'undefined') return null;
                                    const section = document.querySelector(
                                        'filter-wizard .steps > section[style*="display: flex"]'
                                    );
                                    if (!section) return null;
                                    const iffDiv = section.querySelector('[individual-filters]');
                                    if (!iffDiv) return null;
                                    // Get vm scope from the individual-filters element
                                    const iffScope = angular.element(iffDiv).scope();
                                    if (!iffScope) return null;
                                    // Walk up to find vm
                                    let vm = iffScope.vm;
                                    let s = iffScope;
                                    for (let d = 0; !vm && s && d < 5; d++, s = s.$parent) {
                                        vm = s.vm;
                                    }
                                    if (!vm || !vm.selectedList) return null;
                                    // Clear existing selections
                                    const existing = vm.selectedList.length;
                                    vm.selectedList.length = 0;
                                    try { (iffScope.$$phase ? null : iffScope.$apply()); } catch(e) {}
                                    return {ok: true, cleared: existing};
                                }''')
                                if clear_result and clear_result.get('ok'):
                                    self.logger.debug(f"    {pn}: cleared {clear_result.get('cleared',0)} existing field filters")
                                    self.page.wait_for_timeout(300)
                                    break
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # ── Phase 2: Add fields one at a time via csSelect.selectOption ──
                    added_fields = []
                    for cfg in normalized:
                        fid = cfg.get('id', '')
                        try:
                            for f in self.page.frames:
                                try:
                                    add_result = f.evaluate(r'''(fid) => {
                                        if (typeof angular === 'undefined') return null;
                                        const section = document.querySelector(
                                            'filter-wizard .steps > section[style*="display: flex"]'
                                        );
                                        if (!section) return null;
                                        const iffDiv = section.querySelector('[individual-filters]');
                                        if (!iffDiv) return null;
                                        const selEl = iffDiv.querySelector('.csSelect-container');
                                        if (!selEl) return {error: 'no_csSelect_container'};

                                        // csSelect lives on the isolate scope of the csSelect-container
                                        const csScope = angular.element(selEl).isolateScope();
                                        if (!csScope || !csScope.csSelect)
                                            return {error: 'no_csSelect_isolate', keys: Object.keys(
                                                angular.element(selEl).scope() || {}).filter(k=>!k.startsWith('$')).slice(0,15)};

                                        const opts = csScope.csSelect.options || [];
                                        if (!opts.length) return {error: 'no_options'};

                                        // Find the field in available options
                                        const opt = opts.find(o =>
                                            o.id === fid || o.name === fid || o.fieldName === fid ||
                                            (o.combinedName && o.combinedName.includes('(' + fid + ')'))
                                        );
                                        if (!opt)
                                            return {error: 'field_not_found', fid: fid,
                                                    sample: opts.slice(0,5).map(o => ({id:o.id, name:o.name, cn:o.combinedName}))}
;

                                        // Use selectOption to properly trigger Angular bindings + vm.addField()
                                        csScope.csSelect.selectOption(opt);
                                        try { csScope.$apply(); } catch(e) {}
                                        return {ok: true, fid: fid, optId: opt.id, optName: opt.combinedName || opt.name};
                                    }''', fid)
                                    if add_result and add_result.get('ok'):
                                        added_fields.append(fid)
                                        self.logger.debug(f"    {pn}: added field '{fid}' → {add_result.get('optName','')}")
                                        self.page.wait_for_timeout(500)  # Wait for Angular to create accordion
                                        break
                                    elif add_result and add_result.get('error'):
                                        self.logger.debug(f"    {pn}: add field frame skip: {add_result}")
                                except Exception as e:
                                    self.logger.debug(f"    {pn}: add field frame error: {e}")
                        except Exception as e:
                            self.logger.debug(f"    {pn}: add field '{fid}' failed: {e}")

                    if not added_fields:
                        self.logger.warning(f"    {pn}: field_filter could NOT add any fields")
                        continue

                    # ── Phase 3: Configure operator & values for each added field ──
                    for cfg in normalized:
                        fid = cfg.get('id', '')
                        op = cfg.get('operator', '')
                        v1 = cfg.get('value1')
                        v2 = cfg.get('value2')
                        if not op and v1 is None:
                            continue  # No criteria to set
                        if fid not in added_fields:
                            continue  # Wasn't added, skip
                        
                        try:
                            for f in self.page.frames:
                                try:
                                    criteria_result = f.evaluate(r'''(cfg) => {
                                        if (typeof angular === 'undefined') return null;
                                        const section = document.querySelector(
                                            'filter-wizard .steps > section[style*="display: flex"]'
                                        );
                                        if (!section) return null;
                                        const iffDiv = section.querySelector('[individual-filters]');
                                        if (!iffDiv) return null;

                                        // Find the accordion entry for this field
                                        const accordions = iffDiv.querySelectorAll('cs-accordion .accordion--navigation');
                                        if (!accordions.length) return {error: 'no_accordions'};

                                        for (const acc of accordions) {
                                            const filterEl = acc.querySelector('cuic-filter');
                                            if (!filterEl) continue;

                                            // filterCtrl is on the scope (not isolateScope) of cuic-filter
                                            let filterScope = angular.element(filterEl).scope();
                                            if (!filterScope) continue;

                                            // Walk up to find filterCtrl
                                            let fc = filterScope.filterCtrl;
                                            let s = filterScope;
                                            for (let d = 0; !fc && s && d < 5; d++, s = s.$parent) {
                                                fc = s.filterCtrl;
                                            }
                                            if (!fc || !fc.filterField) continue;

                                            const field = fc.filterField;
                                            if (field.id !== cfg.optId && field.name !== cfg.fid &&
                                                !(field.combinedName || '').includes('(' + cfg.fid + ')')) continue;

                                            const result = {ok: true, fid: cfg.fid, fieldId: field.id};

                                            // Set operator via the operator csSelect
                                            if (cfg.operator) {
                                                // Get available operators for this field's filterType
                                                const opOpts = fc.options[field.filterType] || [];
                                                const opMatch = opOpts.find(o => o.operator === cfg.operator);
                                                if (opMatch) {
                                                    field.selected = opMatch;
                                                    // Also try to update operator csSelect if available
                                                    const opSelEl = acc.querySelector('.indFilter_select.csSelect-container');
                                                    if (opSelEl) {
                                                        const opCsScope = angular.element(opSelEl).isolateScope();
                                                        if (opCsScope && opCsScope.csSelect) {
                                                            opCsScope.csSelect.selectOption(opMatch);
                                                        }
                                                    }
                                                    result.operator = cfg.operator;
                                                    result.opLabel = opMatch.label;
                                                } else {
                                                    result.operatorError = 'not_found';
                                                    result.available = opOpts.map(o => o.operator);
                                                }
                                            }

                                            // Set values directly on filterField model
                                            if (cfg.value1 !== undefined && cfg.value1 !== null) {
                                                field.value1 = String(cfg.value1);
                                                result.value1 = field.value1;
                                            }
                                            if (cfg.value2 !== undefined && cfg.value2 !== null) {
                                                field.value2 = String(cfg.value2);
                                                result.value2 = field.value2;
                                            }

                                            // Trigger Angular digest
                                            try {
                                                if (!filterScope.$$phase && !filterScope.$root.$$phase) {
                                                    filterScope.$apply();
                                                }
                                            } catch(e) {}

                                            return result;
                                        }
                                        return {error: 'field_not_found_in_accordions', fid: cfg.fid};
                                    }''', {'fid': fid, 'optId': cfg.get('_optId', ''), 'operator': op,
                                           'value1': v1, 'value2': v2})
                                    if criteria_result and criteria_result.get('ok'):
                                        self.logger.debug(f"    {pn}: field '{fid}' criteria set: op={criteria_result.get('operator','-')}, v1={criteria_result.get('value1','-')}")
                                        break
                                    elif criteria_result and criteria_result.get('error'):
                                        self.logger.debug(f"    {pn}: criteria frame skip: {criteria_result}")
                                except Exception as e:
                                    self.logger.debug(f"    {pn}: criteria frame error: {e}")
                        except Exception as e:
                            self.logger.debug(f"    {pn}: criteria for '{fid}' failed: {e}")

                    self.logger.info(f"    {pn}: field_filter done — added {len(added_fields)} field(s): {added_fields}")

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
          CUIC SPAB (flat):      {"@start_date": "THISDAY", "@agent_list": "all", ...}
          CUIC multi-step:       {"step_1": {...}, "step_2": {...}, ...}
          Step-keyed generic:    {"step_1": {"field_id": val}, ...}
          Flat generic:          {"field_id": val}  (applied to every step)
        """
        try:
            self.page.wait_for_timeout(self.timeout_medium)
            filters = filters or {}

            # Separate metadata from actual filter values
            meta = filters.get('_meta') or {}
            clean = {k: v for k, v in filters.items() if k != '_meta'}
            is_stepped = any(k.startswith('step_') for k in clean)
            wizard_type = meta.get('type', '')

            self.logger.info(f"  Filter wizard: type={wizard_type}, stepped={is_stepped}, "
                             f"keys={list(clean.keys())}")
            for ck, cv in clean.items():
                self.logger.info(f"    filter[{ck}] = {cv}")

            step = 0
            max_steps = 10

            while step < max_steps:
                step += 1

                # Read current step's field structure
                step_info = self._read_wizard_step_fields()

                if step_info:
                    stype = step_info.get('type', 'generic')

                    if stype == 'cuic_multistep':
                        # Multi-step CUIC: filters stored per-step
                        step_key = f'step_{step}'
                        step_vals = clean.get(step_key, {})
                        step_title = step_info.get('stepTitle', f'Step {step}')
                        pnames = [p.get('paramName','') for p in step_info.get('params',[])]
                        self.logger.info(f"  Wizard step {step} '{step_title}' (CUIC multi): params={pnames}")
                        self.logger.info(f"    Saved filter values for {step_key}: {step_vals}")
                        if step_vals:
                            self._apply_filters_to_step(step_info, step_vals)
                        else:
                            self.logger.info(f"    No saved values for {step_key} — using CUIC defaults")

                    elif stype == 'cuic_spab':
                        pnames = [p.get('paramName','') for p in step_info.get('params',[])]
                        self.logger.info(f"  Wizard step {step} (CUIC SPAB): {pnames}")
                        # CUIC SPAB uses flat param-name keys
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

                # Try Next first (middle steps), then Run (last step)
                if self._click_wizard_button('Next'):
                    self.logger.info(f"  Wizard: clicked Next at step {step}")
                    self.page.wait_for_timeout(self.timeout_short)
                elif self._click_wizard_button('Run'):
                    self.logger.info(f"  Wizard: clicked Run at step {step}")
                    break
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

        Returns a unified format:
          {type: 'cuic_spab' | 'cuic_multistep' | 'generic',
           steps: [{step:1, title:'...', params:[...]}],
           datePresets: [...],
           error: ''}

        For SPAB (single-step) reports, there is one step with all params.
        For multi-step wizards, each step has its own params array.
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

                    if stype == 'cuic_multistep':
                        # Multi-step wizard — each call returns one step
                        result['type'] = 'cuic_multistep'
                        step_params = step_info.get('params', [])
                        step_title = step_info.get('stepTitle', f'Step {step}')
                        # Collect datePresets from datetime params
                        for p in step_params:
                            if p.get('type') == 'cuic_datetime' and p.get('datePresets'):
                                result['datePresets'] = p['datePresets']
                        result['steps'].append({
                            'step': step,
                            'title': step_title,
                            'type': 'cuic_multistep',
                            'params': step_params
                        })
                        # Store step titles on first discovery
                        if 'stepTitles' not in result:
                            result['stepTitles'] = step_info.get('stepTitles', [])

                    elif stype == 'cuic_spab':
                        # SPAB single-step wizard — all params on one page
                        result['type'] = 'cuic_spab'
                        result['params'] = step_info.get('params', [])
                        result['datePresets'] = step_info.get('datePresets', [])
                        result['steps'].append({
                            'step': step,
                            'title': 'Parameters',
                            'type': 'cuic_spab',
                            'params': step_info.get('params', [])
                        })
                    else:
                        # Generic HTML fields
                        result['steps'].append({
                            'step': step,
                            'title': f'Step {step}',
                            'fields': step_info.get('fields', [])
                        })

                # Check for Run (last step) — but NOT Next+Run (intermediate)
                has_run = False
                has_next = False
                for f in worker.page.frames:
                    try:
                        for sel in ['button:has-text("Run")', 'input[type="button"][value="Run"]']:
                            btn = f.query_selector(sel)
                            if btn and btn.is_visible():
                                has_run = True
                                break
                        for sel in ['button:has-text("Next")', 'input[type="button"][value="Next"]']:
                            btn = f.query_selector(sel)
                            if btn and btn.is_visible():
                                has_next = True
                                break
                        if has_run:
                            break
                    except Exception:
                        pass

                if has_run and not has_next:
                    # Final step — record but don't click Run
                    break

                # Click Next to advance to the next step
                if has_next:
                    if worker._click_wizard_button('Next'):
                        worker.logger.info(f"  Discovery: clicked Next at step {step}")
                        worker.page.wait_for_timeout(worker.timeout_short)
                    else:
                        break
                elif has_run:
                    # Run is available but Next is too — last functional step
                    break
                else:
                    break

            worker.logger.info(f"Discovery: {len(result['steps'])} wizard step(s) found, type={result['type']}")
            return result

        except Exception as e:
            result['error'] = str(e)
            return result
        finally:
            logout_ok = worker._logout()
            
            if logout_ok:
                # Small delay so logout screen is visible when headless=false
                if worker.page and not worker.page.is_closed():
                    worker.page.wait_for_timeout(1500)
            else:
                # Logout failed — keep browser open for manual intervention
                worker.logger.error("")
                worker.logger.error("="*60)
                worker.logger.error("⚠⚠⚠ KEEPING BROWSER OPEN FOR 60 SECONDS ⚠⚠⚠")
                worker.logger.error("Please manually logout:")
                worker.logger.error("1. Click the user menu (top right)")
                worker.logger.error("2. Click 'Sign Out'")
                worker.logger.error("Or visit: https://148.151.32.77:8444/cuicui/Logout.jsp")
                worker.logger.error("="*60)
                if worker.page and not worker.page.is_closed():
                    worker.page.wait_for_timeout(60000)  # 60 seconds
            
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
