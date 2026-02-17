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

import os
import sys
import time
from typing import Dict, Any, List

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_worker import BaseWorker
from core.config import get_worker_settings, get_worker_credentials
from core.database import log_scrape, has_historical_data

# Import our sub-modules
from . import auth, navigation, wizard, scraper


class Worker(BaseWorker):
    SOURCE_NAME = "cuic"
    DESCRIPTION = "Cisco Unified Intelligence Center Scraper"

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
            logout_ok = auth.logout(self)
            
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
        if not auth.login(self):
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
                    navigation.close_report_page(self)
                    navigation.navigate_to_reports_root(self)

                frame = navigation.get_reports_frame(self)
                if not frame:
                    log_scrape('cuic', label, 'error', 0, time.time() - t0,
                               'Reports iframe not found')
                    continue

                if not navigation.open_report(self, frame, folder, name):
                    log_scrape('cuic', label, 'error', 0, time.time() - t0,
                               f'Could not open {folder}/{name}')
                    continue

                filters = report.get('filters', {})
                if not wizard.run_filter_wizard(self, filters):
                    log_scrape('cuic', label, 'error', 0, time.time() - t0,
                               'Filter wizard failed')
                    continue

                data = scraper.scrape_data(self, label)
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
        navigation.close_report_page(self)
        return all_data

    # ══════════════════════════════════════════════════════════════════════
    #  WIZARD DISCOVERY (called from settings server)
    # ══════════════════════════════════════════════════════════════════════
    @classmethod
    def discover_wizard(cls, report_config: dict) -> dict:
        """Open a report and read all wizard steps' fields.
        Delegates to wizard module."""
        return wizard.discover_wizard(cls, report_config)
