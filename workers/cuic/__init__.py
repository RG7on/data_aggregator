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
import traceback
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

    # CUIC datetime presets that designate a closed (fully past) time window.
    # Used to auto-detect data_type = 'historical' when it is not set in config.
    _HISTORICAL_PRESETS = frozenset({'LASTYR', 'LASTMTH', 'LASTWK', 'LASTQTR'})

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
        self._autodetect_data_types()

    def _autodetect_data_types(self):
        """Auto-classify reports as 'historical' based on their filter presets.

        Only fires when 'data_type' is absent from the report config — explicit
        settings ('ongoing' or 'historical') are always respected.
        """
        for report in self.reports:
            if 'data_type' in report:
                continue
            steps = (report.get('filters') or {}).get('_meta', {}).get('steps', [])
            for step in steps:
                for param in step.get('params', []):
                    preset = (
                        param.get('relativeRange') or
                        param.get('currentPreset') or ''
                    ).upper()
                    if preset in self._HISTORICAL_PRESETS:
                        report['data_type'] = 'historical'
                        self.logger.debug(
                            f"Auto-detected '{report.get('label')}' as historical "
                            f"(filter preset: {preset!r})"
                        )
                        break

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

        self.logger.info(f"Starting CUIC scraper -> {self.url} ({len(enabled)} report(s))")
        try:
            self.setup_browser(ignore_https_errors=True)
            self.logger.info("Browser ready, starting scrape...")
            return self.scrape()
        except Exception as e:
            self.logger.error(f"CUIC worker error: {e}")
            self.logger.error(f"  {traceback.format_exc()}")
            self.screenshot("error", is_step=False)
            return []
        finally:
            logout_ok = auth.logout(self)
            
            if logout_ok:
                # Intentional delay so logout screen is visible in headed mode
                if self.page and not self.page.is_closed():
                    self.page.wait_for_timeout(1500)
            else:
                # Logout failed — keep browser open for manual intervention
                self.logger.error("")
                self.logger.error("="*60)
                self.logger.error("!!! KEEPING BROWSER OPEN FOR 60 SECONDS !!!")
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

            self.logger.info("=" * 60)
            self.logger.info(f"Report {i+1}/{len(enabled)}: {label}")
            self.logger.info(f"  Folder: {folder}")
            self.logger.info(f"  Name:   {name}")
            self.logger.info(f"  Type:   {report.get('data_type', 'ongoing')}")
            filter_keys = list((report.get('filters') or {}).keys())
            self.logger.info(f"  Filter keys: {filter_keys}")
            self.logger.info("=" * 60)
            t0 = time.time()

            if report.get('data_type') == 'historical':
                if has_historical_data('cuic', label):
                    self.logger.info(f"Report '{label}': HISTORICAL - already scraped, skipping")
                    log_scrape('cuic', label, 'skipped', 0, 0, 'Historical data already exists')
                    continue

            try:
                if i > 0:
                    self.logger.info("Closing previous report and navigating back...")
                    navigation.close_report_page(self)
                    navigation.navigate_to_reports_root(self)

                self.logger.info("Getting reports iframe...")
                frame = navigation.get_reports_frame(self)
                if not frame:
                    self.logger.error(f"Reports iframe not found for '{label}'")
                    self.screenshot(f"r{i+1}_no_iframe", is_step=False)
                    log_scrape('cuic', label, 'error', 0, time.time() - t0,
                               'Reports iframe not found')
                    continue

                self.logger.info(f"Opening report '{name}' in folder '{folder}'...")
                if not navigation.open_report(self, frame, folder, name):
                    self.logger.error(f"Could not open {folder}/{name}")
                    self.screenshot(f"r{i+1}_open_failed", is_step=False)
                    log_scrape('cuic', label, 'error', 0, time.time() - t0,
                               f'Could not open {folder}/{name}')
                    continue

                self.logger.info("Running filter wizard...")
                filters = report.get('filters', {})
                if not wizard.run_filter_wizard(self, filters):
                    self.logger.error(f"Filter wizard failed for '{label}'")
                    log_scrape('cuic', label, 'error', 0, time.time() - t0,
                               'Filter wizard failed')
                    continue

                self.logger.info("Scraping report data...")
                data = scraper.scrape_data(self, label)
                elapsed = time.time() - t0

                if data:
                    all_data.extend(data)
                    log_scrape('cuic', label, 'success', len(data), elapsed, '')
                    self.logger.info(
                        f"[OK] Report '{label}': {len(data)} records in {elapsed:.1f}s")
                else:
                    self.logger.warning(f"Report '{label}': no data returned after {elapsed:.1f}s")
                    self.screenshot(f"r{i+1}_no_data", is_step=False)
                    log_scrape('cuic', label, 'no_data', 0, elapsed, 'No data found')

            except Exception as e:
                elapsed = time.time() - t0
                log_scrape('cuic', label, 'error', 0, elapsed, str(e))
                self.logger.error(f"Report '{label}' failed after {elapsed:.1f}s: {e}")
                self.logger.error(f"  {traceback.format_exc()}")
                self.screenshot(f"r{i+1}_exception", is_step=False)

        navigation.close_report_page(self)
        self.logger.info(f"Scrape complete: {len(all_data)} total records from {len(enabled)} report(s)")
        return all_data

    # ══════════════════════════════════════════════════════════════════════
    #  WIZARD DISCOVERY (called from settings server)
    # ══════════════════════════════════════════════════════════════════════
    @classmethod
    def discover_wizard(cls, report_config: dict) -> dict:
        """Open a report and read all wizard steps' fields.
        Delegates to wizard module."""
        return wizard.discover_wizard(cls, report_config)
