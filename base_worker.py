"""
Base Worker Class for Modular Snapshot Scraper
===============================================
All workers must inherit from this class and implement the scrape() method.
Handles common operations like browser setup, login patterns, and error handling.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


class BaseWorker(ABC):
    """
    Abstract base class for all scraper workers.
    
    Each worker must:
    1. Define a unique SOURCE_NAME (used as identifier in CSV)
    2. Implement the scrape() method that returns a dict of KPIs
    
    The base class provides:
    - Playwright browser management (headless Chromium)
    - Common login helper methods
    - Error handling and logging
    """
    
    # Must be overridden by each worker
    SOURCE_NAME: str = "base_worker"
    DESCRIPTION: str = "Base worker class - do not use directly"
    
    def __init__(self):
        self.logger = logging.getLogger(self.SOURCE_NAME)
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._playwright = None
    
    def setup_browser(self, headless: bool = True, use_system_chrome: bool = True) -> Page:
        """
        Initialize Playwright browser with common settings.
        
        Args:
            headless: Run browser in headless mode
            use_system_chrome: Use system Chrome instead of Playwright's Chromium
            
        Returns a Page object ready for navigation.
        """
        self._playwright = sync_playwright().start()
        
        # Try to use system Chrome first (better compatibility)
        if use_system_chrome:
            try:
                self.browser = self._playwright.chromium.launch(
                    channel="chrome",  # Use system Chrome
                    headless=headless,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-dev-shm-usage'
                    ]
                )
                self.logger.info("Using system Chrome browser")
            except Exception as e:
                self.logger.warning(f"Could not launch system Chrome: {e}")
                self.logger.info("Falling back to Playwright Chromium")
                self.browser = self._playwright.chromium.launch(
                    headless=headless,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-dev-shm-usage'
                    ]
                )
        else:
            # Use Playwright's bundled Chromium
            self.browser = self._playwright.chromium.launch(
                headless=headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage'
                ]
            )
        
        self.context = self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        self.page = self.context.new_page()
        self.logger.info("Browser initialized successfully")
        return self.page
    
    def teardown_browser(self):
        """
        Clean up browser resources. Each step is wrapped individually
        so a failure in one doesn't leave the others as zombies.
        """
        for name, obj, method in [
            ("page",     self.page,        "close"),
            ("context",  self.context,     "close"),
            ("browser",  self.browser,     "close"),
            ("playwright", self._playwright, "stop"),
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
    
    def login_with_form(
        self,
        url: str,
        username: str,
        password: str,
        username_selector: str,
        password_selector: str,
        submit_selector: str,
        success_indicator: str,
        timeout: int = 30000
    ) -> bool:
        """
        Generic form-based login helper.
        
        Args:
            url: Login page URL
            username: Username/email to enter
            password: Password to enter
            username_selector: CSS selector for username field
            password_selector: CSS selector for password field
            submit_selector: CSS selector for submit button
            success_indicator: CSS selector that appears after successful login
            timeout: Max wait time in milliseconds
            
        Returns:
            True if login successful, False otherwise
        """
        try:
            self.page.goto(url, wait_until='networkidle', timeout=timeout)
            self.page.fill(username_selector, username)
            self.page.fill(password_selector, password)
            self.page.click(submit_selector)
            
            # Wait for success indicator
            self.page.wait_for_selector(success_indicator, timeout=timeout)
            self.logger.info(f"Login successful for {self.SOURCE_NAME}")
            return True
            
        except Exception as e:
            self.logger.error(f"Login failed: {e}")
            return False
    
    def safe_get_text(self, selector: str, default: str = "0") -> str:
        """
        Safely extract text from an element.
        Returns default value if element not found.
        """
        try:
            element = self.page.query_selector(selector)
            if element:
                return element.inner_text().strip()
            return default
        except Exception as e:
            self.logger.warning(f"Could not get text from {selector}: {e}")
            return default
    
    def safe_get_number(self, selector: str, default: int = 0) -> int:
        """
        Safely extract a number from an element.
        Handles common formats like "102 tickets" -> 102
        """
        try:
            text = self.safe_get_text(selector, str(default))
            # Extract digits from the text
            import re
            numbers = re.findall(r'\d+', text.replace(',', ''))
            if numbers:
                return int(numbers[0])
            return default
        except Exception as e:
            self.logger.warning(f"Could not parse number from {selector}: {e}")
            return default
    
    def wait_for_data_load(self, indicator_selector: str, timeout: int = 30000):
        """Wait for a specific element indicating data has loaded."""
        try:
            self.page.wait_for_selector(indicator_selector, timeout=timeout)
        except Exception as e:
            self.logger.warning(f"Timeout waiting for {indicator_selector}: {e}")
    
    @abstractmethod
    def scrape(self) -> Dict[str, Any]:
        """
        Main scraping method - MUST be implemented by each worker.
        
        Returns:
            Dictionary with KPI names as keys and values.
            Example: {'smax_tickets': 102, 'smax_open_requests': 45}
            
        Note:
            - Keys should be lowercase with underscores (snake_case)
            - Keys should be prefixed with source name for clarity
            - Values should be numeric where possible
        """
        pass
    
    def run(self) -> Dict[str, Any]:
        """
        Execute the worker with proper setup and teardown.
        This is the method called by the driver.
        
        Returns:
            Dictionary with scraped data, or empty dict on failure
        """
        result = {}
        try:
            self.setup_browser(headless=True)
            result = self.scrape()
            self.logger.info(f"Scrape completed: {result}")
        except Exception as e:
            self.logger.error(f"Worker failed: {e}")
            result = {}
        finally:
            self.teardown_browser()
        
        return result
    
    def get_metadata(self) -> Dict[str, str]:
        """Return worker metadata for documentation."""
        return {
            'source_name': self.SOURCE_NAME,
            'description': self.DESCRIPTION
        }
