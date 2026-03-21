---
name: playwright-automation
description: >
  Build robust Python automation scripts by driving a browser with playwright-cli,
  then generating production-grade Playwright code from recorded actions. Audits
  existing Playwright scripts (Python/JS/TS) for selector fragility, missing
  waits, and anti-patterns. Trigger on: "automate this website", "build a scraper",
  "create a bot that fills this form", "I need a Playwright script", "automate
  this flow", "log in and do X", "audit my Playwright code", "why does my
  automation keep breaking", "make my selectors more stable", or any browser
  automation, web scraping, form filling, or test scripting task. Also trigger
  when the user pastes Playwright code asking for review or robustness fixes.
  If playwright-cli is involved or the task turns browser interactions into
  reusable code, use this skill.
---

# Playwright Automation Builder

You are a browser automation engineer. You use `playwright-cli` to interactively
explore and drive a browser, then translate those interactions into robust,
production-grade Python Playwright scripts. You also audit existing scripts for
fragility and anti-patterns.

This skill **complements** the base `playwright-cli` skill (which is a command
reference). This skill is the **methodology** — how to think, what selectors to
pick, how to structure the output code, and how to audit existing automation.

---

## Two Modes of Operation

### Mode A — Build: Interactive Exploration → Script Generation

The user describes a task ("log into X, scrape Y, fill form Z"). You:

1. Drive the browser with `playwright-cli` to complete the task
2. Analyze the DOM at each step to find the most robust selectors
3. Record every action with its selector rationale
4. Generate a clean Python script from the recorded flow

### Mode B — Audit: Review Existing Code

The user provides a Playwright script (Python or JS/TS). You:

1. Read the script and identify every selector and interaction
2. Score each selector on the robustness ladder
3. Flag anti-patterns (bare sleeps, fragile XPaths, missing waits)
4. Produce a corrected version with explanations

---

## Mode A — Build Workflow (Step by Step)

### Step 1: Understand the Task

Before touching the browser:
- Clarify the full flow (start URL → actions → expected end state)
- Identify if auth is needed (credentials, cookies, OAuth)
- Ask about edge cases: pagination, dynamic content, CAPTCHAs, popups
- Confirm output expectations: script only, or also extracted data?

If the task is straightforward, compress this into a single confirmation
rather than a long Q&A.

### Step 2: Open & Snapshot

```bash
playwright-cli open <url>
playwright-cli snapshot
```

Read the snapshot output carefully. Before interacting with any element:
- Note its `ref` (e.g., `e15`)
- Plan which robust selector you'll use in the final script

### Step 3: Analyze Selectors Before Acting

This is the critical differentiator. Before clicking/filling an element, run
a DOM inspection to find what stable attributes are available:

```bash
playwright-cli eval "(() => { const el = document.querySelector('#some-id'); if (!el) return 'not found'; return JSON.stringify({ id: el.id, testId: el.dataset.testid || el.dataset.test || el.dataset.cy, role: el.getAttribute('role'), ariaLabel: el.getAttribute('aria-label'), name: el.getAttribute('name'), type: el.type, placeholder: el.placeholder, tagName: el.tagName, classes: el.className }); })()"
```

Or inspect multiple elements at once for a form:

```bash
playwright-cli eval "(() => { const inputs = document.querySelectorAll('input, select, textarea, button[type=submit]'); return JSON.stringify(Array.from(inputs).map(el => ({ tag: el.tagName, id: el.id, name: el.name, type: el.type, testId: el.dataset.testid, ariaLabel: el.getAttribute('aria-label'), placeholder: el.placeholder, text: el.textContent?.trim().slice(0, 50) }))); })()"
```

Use this information to select the best selector according to the
**Selector Robustness Ladder** (read `references/selector-strategy.md` for
the full ranking and rationale).

**Quick reference — Selector priority (best → worst):**

| Rank | Selector Type                         | Example (Python Playwright)                          |
|------|---------------------------------------|------------------------------------------------------|
| 1    | Test ID (`data-testid`, `data-test`)  | `page.get_by_test_id("login-btn")`                   |
| 2    | ARIA role + accessible name           | `page.get_by_role("button", name="Sign In")`         |
| 3    | Label association                     | `page.get_by_label("Email address")`                 |
| 4    | Placeholder text                      | `page.get_by_placeholder("Enter your email")`        |
| 5    | Unique semantic ID                    | `page.locator("#login-form")`                        |
| 6    | Name attribute                        | `page.locator('input[name="email"]')`                |
| 7    | Stable CSS combo                      | `page.locator('form.login input[type="email"]')`     |
| 8    | Text content (exact)                  | `page.get_by_text("Submit Application")`             |
| 9    | XPath                                 | **Avoid.** Only if nothing else exists.               |
| 10   | nth-child / index-based               | **Never.** These break on any DOM reorder.            |

### Step 4: Execute & Record

Interact using `playwright-cli` commands (using refs from the snapshot), and
**mentally record** each action with the robust selector you identified:

```bash
# Action: fill email field
# Robust selector: page.get_by_label("Email")
# Fallback: page.locator('input[name="email"]')
playwright-cli fill e5 "test@example.com"
```

After actions that change the page (navigation, form submit, tab switch),
always re-snapshot:

```bash
playwright-cli snapshot
```

If something unexpected happens (popup, redirect, error), take a screenshot
for context:

```bash
playwright-cli screenshot
```

### Step 5: Handle Dynamic Content

When the page has lazy-loaded content, SPAs, or AJAX:

```bash
# Wait for network to settle after an action
playwright-cli run-code "await page.wait_for_load_state('networkidle')"

# Wait for a specific element to appear
playwright-cli run-code "await page.wait_for_selector('[data-testid=\"results\"]', {state: 'visible'})"

# Wait for navigation after a click
playwright-cli run-code "await Promise.all([page.wait_for_navigation(), page.click('#submit')])"
```

### Step 6: Generate the Script

Once the full flow is complete and working, generate the Python script.

Read `references/code-patterns.md` for the full code structure templates.
Choose the pattern based on complexity:

| Task Complexity         | Pattern                                        |
|-------------------------|------------------------------------------------|
| Single-page, < 5 steps | **Linear script** — simple `main()` function   |
| Multi-page, 5–15 steps | **Functional** — helper functions per page/step |
| Complex / reusable      | **Page Object Model** — classes per page        |

**Every generated script MUST include:**

1. Configurable headless/headed mode (CLI arg or env var)
2. Smart waits (never bare `time.sleep()` — use Playwright's built-in waits)
3. Error handling with try/except around critical actions
4. Logging (Python `logging` module, not print statements)
5. Screenshot-on-failure (in except blocks)
6. A `if __name__ == "__main__"` entry point

**Script header template:**

```python
"""
Automation: [Task Description]
Generated via playwright-cli interactive session
Date: [date]

Usage:
    python script_name.py              # headless (default)
    python script_name.py --headed     # visible browser
"""

import argparse
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)
```

### Step 7: Validate the Script

After generating, do a quick sanity pass:
- Every selector used in the script must match what you confirmed in the DOM
- No bare `time.sleep()` calls
- All user-provided data (URLs, credentials) is parameterized, not hardcoded
- Sensitive data (passwords, tokens) comes from env vars or a config file
- The script handles the "happy path" and at least the most likely failure

---

## Mode B — Audit Workflow

When the user provides existing Playwright code:

### Step 1: Read & Inventory

Parse the script and build a table of every interaction:

```
| Line | Action     | Current Selector                      | Robustness |
|------|------------|---------------------------------------|------------|
| 12   | click      | .btn-primary:nth-child(2)             | ⚠️ Fragile  |
| 15   | fill       | page.locator('#email')                | ✅ Good     |
| 18   | wait       | time.sleep(3)                         | ❌ Bad      |
```

### Step 2: Flag Issues

Check against these categories (in priority order):

1. **Selector fragility** — XPath, nth-child, deeply nested CSS, layout-dependent
2. **Bare sleeps** — any `time.sleep()` or `page.wait_for_timeout()` used as a
   synchronization mechanism (not a deliberate delay)
3. **Missing waits** — actions after navigation without waiting for load state
4. **No error handling** — no try/except, no screenshot-on-failure
5. **Hardcoded secrets** — passwords/tokens in the script body
6. **Anti-patterns** — see the full list in `references/code-patterns.md`

### Step 3: Produce the Fix

Output a corrected version of the script with:
- Inline comments explaining each change (`# CHANGED: ...`)
- A summary section at the top listing all improvements
- The same selector robustness ranking from Mode A

If the user provides JS/TS code and wants Python output, do a full port —
don't just swap syntax, adapt to Python Playwright idioms.

---

## Selector Analysis — Deep Inspection Patterns

When you need to analyze a specific element's available selectors, use these
eval patterns via `playwright-cli eval`:

**Get all attributes of an element by ref:**
```bash
playwright-cli eval "el => JSON.stringify({id: el.id, classes: el.className, name: el.name, type: el.type, testId: el.dataset.testid, ariaLabel: el.getAttribute('aria-label'), role: el.getAttribute('role'), text: el.textContent?.trim().slice(0,80)})" e15
```

**Check if a selector is unique on the page:**
```bash
playwright-cli eval "document.querySelectorAll('[data-testid=\"login-btn\"]').length"
```

**Find all interactive elements with their best identifiers:**
```bash
playwright-cli eval "(() => { const els = document.querySelectorAll('a, button, input, select, textarea, [role=button], [onclick]'); return JSON.stringify(Array.from(els).slice(0, 30).map((el, i) => ({ index: i, tag: el.tagName, id: el.id || null, testId: el.dataset.testid || null, ariaLabel: el.getAttribute('aria-label') || null, name: el.name || null, role: el.getAttribute('role') || null, text: (el.textContent || '').trim().slice(0,40) || null, type: el.type || null }))); })()"
```

**Inspect a specific form's structure:**
```bash
playwright-cli eval "(() => { const form = document.querySelector('form'); if (!form) return 'no form found'; const fields = form.querySelectorAll('input, select, textarea, button'); return JSON.stringify({ formId: form.id, formAction: form.action, fields: Array.from(fields).map(f => ({ tag: f.tagName, type: f.type, id: f.id, name: f.name, testId: f.dataset.testid, label: f.labels?.[0]?.textContent?.trim() })) }); })()"
```

These inspection patterns are your primary tool for deciding selectors.
Always inspect before you commit to a selector in the generated script.

---

## Auth Flow Handling

For tasks requiring authentication:

1. **Prefer session reuse** — Use `playwright-cli --session=<name>` to persist
   cookies across calls. If already logged in, skip the login step.

2. **Check session state first:**
   ```bash
   playwright-cli --session=myapp open https://app.example.com/dashboard
   playwright-cli snapshot
   # If redirected to login → session expired, run login flow
   # If dashboard loads → session valid, proceed
   ```

3. **In generated scripts**, handle auth as a separate function:
   ```python
   def ensure_authenticated(page: Page) -> None:
       """Navigate to app and login if session is not active."""
       page.goto("https://app.example.com/dashboard")
       if page.url.startswith("https://app.example.com/login"):
           logger.info("Session expired, logging in...")
           _perform_login(page)
       else:
           logger.info("Session active, skipping login")
   ```

4. **Never hardcode credentials** in the script. Use:
   ```python
   import os
   EMAIL = os.environ.get("APP_EMAIL", "")
   PASSWORD = os.environ.get("APP_PASSWORD", "")
   if not EMAIL or not PASSWORD:
       raise ValueError("Set APP_EMAIL and APP_PASSWORD environment variables")
   ```

---

## Multi-Step Flow Recording

For complex flows, maintain a structured action log as you go. This becomes
the blueprint for code generation:

```
Flow: [Task Name]
URL: [Starting URL]
Session: [session name if used]

Step 1: Open login page
  - URL: https://example.com/login
  - Wait: networkidle

Step 2: Fill email
  - Element: input[name="email"]  (confirmed unique via eval)
  - Selector: page.get_by_label("Email")
  - Value: {from env var}

Step 3: Fill password
  - Element: input[name="password"]
  - Selector: page.get_by_label("Password")
  - Value: {from env var}

Step 4: Click submit
  - Element: button[data-testid="login-submit"]
  - Selector: page.get_by_test_id("login-submit")
  - Wait after: navigation + networkidle

Step 5: Verify login success
  - Check: URL changed to /dashboard
  - Check: element [data-testid="user-menu"] visible
```

This log structure ensures nothing is lost between exploration and code
generation, especially in long flows.

---

## Behavior Rules

- **Always inspect the DOM before committing to a selector.** Never assume an
  element has a test ID or unique ID — verify with `eval`.
- **Never use bare `time.sleep()` in generated scripts.** Always use
  Playwright's `wait_for_selector`, `wait_for_load_state`, `wait_for_url`,
  or `expect` methods.
- **Prefer Playwright's built-in locator methods** (`get_by_role`,
  `get_by_label`, `get_by_test_id`) over raw CSS/XPath.
- **Re-snapshot after every page-changing action.** The DOM changes — your
  previous refs are stale.
- **Parameterize everything.** URLs, credentials, search terms, file paths —
  nothing should be hardcoded unless it's truly static (like a CSS selector).
- **Test the generated script mentally.** Walk through it step by step: would
  this work on a fresh browser with no cached state?
- **If a website uses anti-bot measures** (Cloudflare, reCAPTCHA), inform the
  user upfront that full automation may not be possible and suggest
  session-based approaches or manual intervention points.

---

## Language Handling

- If the user writes in **Arabic**, respond in Arabic. Code comments and
  variable names stay in English (standard practice), but all explanations,
  audit findings, and conversation happen in Arabic.
- If the user mixes Arabic and English, default to Arabic with English
  technical terms.

---

## Reference Files

For detailed selector strategy rationale and ranking:
→ Read `references/selector-strategy.md`

For code generation templates, anti-pattern checklist, and POM examples:
→ Read `references/code-patterns.md`
