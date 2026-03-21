# Code Patterns & Templates

Code generation templates for different complexity levels, plus the anti-pattern
checklist for auditing existing scripts.

---

## Table of Contents

1. [Pattern A — Linear Script](#pattern-a--linear-script)
2. [Pattern B — Functional (Helper Functions)](#pattern-b--functional)
3. [Pattern C — Page Object Model](#pattern-c--page-object-model)
4. [Anti-Pattern Checklist](#anti-pattern-checklist)
5. [Common Wait Strategies](#common-wait-strategies)
6. [Error Handling Patterns](#error-handling-patterns)
7. [Data Extraction Patterns](#data-extraction-patterns)

---

## Pattern A — Linear Script

**Use when:** Single-page task, < 5 interactions, no reuse needed.

```python
"""
Automation: [Short description]
Generated via playwright-cli interactive session

Usage:
    python script.py                # headless
    python script.py --headed       # visible browser
    python script.py --slow-mo 500  # slow for debugging
"""

import argparse
import logging
import os
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

SCREENSHOT_DIR = "screenshots"


def parse_args():
    parser = argparse.ArgumentParser(description="[Task description]")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser")
    parser.add_argument("--slow-mo", type=int, default=0, help="Slow down actions by ms")
    return parser.parse_args()


def main():
    args = parse_args()
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not args.headed,
            slow_mo=args.slow_mo
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()

        try:
            # Step 1: Navigate
            logger.info("Navigating to [URL]")
            page.goto("https://example.com", wait_until="domcontentloaded")

            # Step 2: [Action]
            logger.info("[Describe action]")
            page.get_by_label("Email").fill("user@example.com")

            # Step 3: [Action]
            logger.info("[Describe action]")
            page.get_by_role("button", name="Submit").click()

            # Step 4: Verify success
            page.wait_for_url("**/success**")
            logger.info("Task completed successfully")

        except PlaywrightTimeout as e:
            logger.error(f"Timeout: {e}")
            page.screenshot(path=f"{SCREENSHOT_DIR}/timeout_error.png")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            page.screenshot(path=f"{SCREENSHOT_DIR}/unexpected_error.png")
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
```

---

## Pattern B — Functional

**Use when:** Multi-page flow, 5–15 steps, logical groupings by page/section.

```python
"""
Automation: [Multi-step flow description]
Generated via playwright-cli interactive session

Usage:
    python script.py                          # headless
    python script.py --headed                 # visible browser
    APP_EMAIL=x APP_PASSWORD=y python script.py  # with credentials
"""

import argparse
import logging
import os
import sys
from playwright.sync_api import Page, sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

SCREENSHOT_DIR = "screenshots"
BASE_URL = os.environ.get("APP_URL", "https://example.com")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--slow-mo", type=int, default=0)
    return parser.parse_args()


def screenshot_on_error(page: Page, name: str):
    """Capture a screenshot for debugging."""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = f"{SCREENSHOT_DIR}/{name}.png"
    try:
        page.screenshot(path=path)
        logger.info(f"Screenshot saved: {path}")
    except Exception:
        logger.warning(f"Could not save screenshot: {path}")


def login(page: Page) -> None:
    """Authenticate if session is not active."""
    email = os.environ.get("APP_EMAIL")
    password = os.environ.get("APP_PASSWORD")
    if not email or not password:
        raise ValueError("Set APP_EMAIL and APP_PASSWORD environment variables")

    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")

    # Check if already logged in (redirect to dashboard)
    if "/dashboard" in page.url:
        logger.info("Already authenticated")
        return

    logger.info("Logging in...")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign In").click()
    page.wait_for_url("**/dashboard**", timeout=10000)
    logger.info("Login successful")


def navigate_to_section(page: Page) -> None:
    """Navigate to the target section."""
    logger.info("Navigating to [section]...")
    page.get_by_role("link", name="[Section Name]").click()
    page.wait_for_load_state("networkidle")


def perform_task(page: Page) -> dict:
    """Execute the core task. Returns result data."""
    logger.info("Performing [task]...")

    # ... actions ...

    return {"status": "success"}


def main():
    args = parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not args.headed,
            slow_mo=args.slow_mo
        )
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()

        try:
            login(page)
            navigate_to_section(page)
            result = perform_task(page)
            logger.info(f"Result: {result}")

        except PlaywrightTimeout as e:
            logger.error(f"Timeout during automation: {e}")
            screenshot_on_error(page, "timeout")
            sys.exit(1)
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            screenshot_on_error(page, "error")
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
```

---

## Pattern C — Page Object Model

**Use when:** Complex flows, multiple pages, reusable across different scripts,
or the automation will be maintained long-term.

```python
"""
Page Object Model base for [Application Name]
"""

import logging
import os
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)
SCREENSHOT_DIR = "screenshots"


class BasePage:
    """Base class for all page objects."""

    def __init__(self, page: Page):
        self.page = page

    def screenshot_on_error(self, name: str) -> None:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        path = f"{SCREENSHOT_DIR}/{name}.png"
        try:
            self.page.screenshot(path=path)
            logger.info(f"Screenshot saved: {path}")
        except Exception:
            logger.warning(f"Could not save screenshot: {path}")

    def safe_click(self, locator, timeout: int = 5000) -> None:
        """Click with automatic wait and error screenshot."""
        try:
            locator.click(timeout=timeout)
        except PlaywrightTimeout:
            self.screenshot_on_error("click_timeout")
            raise

    def safe_fill(self, locator, value: str, timeout: int = 5000) -> None:
        """Fill with automatic wait and error screenshot."""
        try:
            locator.fill(value, timeout=timeout)
        except PlaywrightTimeout:
            self.screenshot_on_error("fill_timeout")
            raise


class LoginPage(BasePage):
    """Login page interactions."""

    URL = "https://example.com/login"

    @property
    def email_field(self):
        return self.page.get_by_label("Email")

    @property
    def password_field(self):
        return self.page.get_by_label("Password")

    @property
    def submit_button(self):
        return self.page.get_by_role("button", name="Sign In")

    def navigate(self) -> None:
        self.page.goto(self.URL, wait_until="domcontentloaded")

    def login(self, email: str, password: str) -> "DashboardPage":
        logger.info("Performing login...")
        self.safe_fill(self.email_field, email)
        self.safe_fill(self.password_field, password)
        self.safe_click(self.submit_button)
        self.page.wait_for_url("**/dashboard**", timeout=10000)
        logger.info("Login successful")
        return DashboardPage(self.page)


class DashboardPage(BasePage):
    """Dashboard page interactions."""

    @property
    def user_menu(self):
        return self.page.get_by_test_id("user-menu")

    @property
    def nav_links(self):
        return self.page.get_by_role("navigation").get_by_role("link")

    def is_loaded(self) -> bool:
        try:
            self.user_menu.wait_for(state="visible", timeout=5000)
            return True
        except PlaywrightTimeout:
            return False

    def navigate_to(self, section_name: str) -> None:
        logger.info(f"Navigating to {section_name}...")
        self.page.get_by_role("link", name=section_name).click()
        self.page.wait_for_load_state("networkidle")
```

**Main script using POM:**

```python
import argparse
import logging
import os
import sys
from playwright.sync_api import sync_playwright
from pages.login_page import LoginPage
from pages.dashboard_page import DashboardPage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    email = os.environ.get("APP_EMAIL")
    password = os.environ.get("APP_PASSWORD")
    if not email or not password:
        raise ValueError("Set APP_EMAIL and APP_PASSWORD env vars")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_context().new_page()

        try:
            login_page = LoginPage(page)
            login_page.navigate()
            dashboard = login_page.login(email, password)

            if not dashboard.is_loaded():
                raise RuntimeError("Dashboard did not load after login")

            dashboard.navigate_to("Reports")
            # ... continue flow ...

        except Exception as e:
            logger.error(f"Automation failed: {e}")
            page.screenshot(path="screenshots/fatal.png")
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
```

---

## Anti-Pattern Checklist

Use this when auditing existing scripts. Each item is a red flag.

### Critical (Fix immediately)

| # | Anti-Pattern | Why It's Bad | Fix |
|---|-------------|--------------|-----|
| 1 | `time.sleep(N)` | Wastes time or races. Never reliable. | Use `wait_for_selector`, `wait_for_load_state`, `wait_for_url` |
| 2 | `page.wait_for_timeout(N)` as sync | Same as sleep — Playwright's version of it | Same as above |
| 3 | XPath with structure: `//div[3]/div/a` | Breaks on any DOM change | Replace with semantic selector |
| 4 | Hardcoded passwords/tokens | Security risk | Move to env vars |
| 5 | No error handling | Script crashes silently | Add try/except + screenshot |
| 6 | `.nth(N)` on broad locators | Index-dependent, breaks on reorder | Find unique selector |

### Important (Fix before production)

| # | Anti-Pattern | Why It's Bad | Fix |
|---|-------------|--------------|-----|
| 7 | Utility CSS classes (`.mt-4.flex`) | Change constantly with styling | Use semantic selectors |
| 8 | Auto-generated IDs (`#react-select-3`) | Change on re-render | Use label, role, or testid |
| 9 | No `wait_until` on `goto()` | Page may not be ready | Add `wait_until="domcontentloaded"` |
| 10 | Clicking without waiting for element | Element might not be visible yet | Use `locator.click()` which auto-waits |
| 11 | `print()` instead of `logging` | No log levels, no timestamps | Use `logging` module |
| 12 | No viewport set | Different layouts in headless | Set explicit viewport size |

### Nice to Have

| # | Anti-Pattern | Fix |
|---|-------------|-----|
| 13 | No CLI args for headed/headless | Add `argparse` with `--headed` flag |
| 14 | No screenshot directory | Create `screenshots/` in setup |
| 15 | Magic strings repeated | Extract to constants at top of file |
| 16 | Single monolithic function | Break into logical steps (Pattern B) |

---

## Common Wait Strategies

Choose the right wait for the situation:

```python
# After navigation (clicking a link that loads a new page)
page.wait_for_load_state("domcontentloaded")  # DOM parsed, not all resources
page.wait_for_load_state("load")               # All resources loaded
page.wait_for_load_state("networkidle")         # No network for 500ms (SPAs)

# After an action that triggers content to appear
page.wait_for_selector('[data-testid="results"]', state="visible")

# After an action that triggers a URL change
page.wait_for_url("**/dashboard**")
page.wait_for_url(lambda url: "/success" in url)

# After an action that triggers an API call
with page.expect_response("**/api/data**") as response_info:
    page.get_by_role("button", name="Load").click()
response = response_info.value

# Waiting for an element to disappear (loading spinner)
page.wait_for_selector(".spinner", state="hidden")

# Combined: click + wait for navigation
with page.expect_navigation():
    page.get_by_role("link", name="Dashboard").click()
```

**The golden rule:** Wait for the *specific thing you need*, not for time to
pass. If you're waiting for search results, wait for the results container.
If you're waiting for a redirect, wait for the URL. Never just sleep.

---

## Error Handling Patterns

### Retry Pattern (for flaky elements)

```python
from playwright.sync_api import TimeoutError as PlaywrightTimeout

def retry_action(action, max_retries: int = 3, delay_ms: int = 1000):
    """Retry a Playwright action with backoff."""
    for attempt in range(max_retries):
        try:
            return action()
        except PlaywrightTimeout:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Attempt {attempt + 1} failed, retrying...")
            page.wait_for_timeout(delay_ms * (attempt + 1))

# Usage
retry_action(lambda: page.get_by_role("button", name="Submit").click())
```

### Conditional Flow (element may or may not appear)

```python
# Cookie consent popup — dismiss if present, ignore if not
cookie_banner = page.locator('[data-testid="cookie-consent"]')
if cookie_banner.is_visible():
    cookie_banner.get_by_role("button", name="Accept").click()
    logger.info("Dismissed cookie banner")

# Or with a short timeout
try:
    page.get_by_role("dialog").get_by_text("Accept").click(timeout=3000)
    logger.info("Dismissed popup")
except PlaywrightTimeout:
    logger.info("No popup appeared, continuing")
```

---

## Data Extraction Patterns

### Extract table data

```python
def extract_table(page: Page, table_selector: str) -> list[dict]:
    """Extract all rows from an HTML table as dicts."""
    headers = page.locator(f"{table_selector} thead th").all_text_contents()
    rows = page.locator(f"{table_selector} tbody tr").all()
    data = []
    for row in rows:
        cells = row.locator("td").all_text_contents()
        data.append(dict(zip(headers, cells)))
    return data
```

### Extract list items

```python
items = page.locator('[data-testid="product-card"]').all()
products = []
for item in items:
    products.append({
        "name": item.locator("h3").text_content().strip(),
        "price": item.locator(".price").text_content().strip(),
        "link": item.locator("a").get_attribute("href"),
    })
```

### Paginated extraction

```python
all_data = []
while True:
    all_data.extend(extract_current_page(page))
    next_btn = page.get_by_role("button", name="Next")
    if next_btn.is_disabled():
        break
    next_btn.click()
    page.wait_for_load_state("networkidle")
    logger.info(f"Page loaded, total items: {len(all_data)}")
```
