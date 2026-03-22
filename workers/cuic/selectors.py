"""
CUIC Selectors
==============
Centralized selectors for the CUIC worker modules.

Selector priority (most → least robust):
  data attributes > ARIA roles > stable text anchors > CSS class > XPath
"""

# ── Login (Stage 1: username → Next) ─────────────────────────────
USERNAME_SELECTOR = 'input[placeholder="Enter Username"]'
NEXT_BTN_SELECTOR = 'button:has-text("Next")'

# ── Login (Stage 2: password + LDAP → Sign In) ──────────────────
PASSWORD_SELECTOR = 'input[type="password"]'
DOMAIN_SELECT_SELECTOR = 'select:visible'
SIGN_IN_BTN_SELECTOR = 'button:has-text("Sign In")'

# Fallback chains (tried in order if primary selector fails)
USERNAME_FALLBACKS = [
    'input[placeholder="Enter Username"]',  # placeholder text (from screenshot)
    'input[type="text"]:visible',            # only visible text input
    'form input:first-of-type',              # first input in form
]
NEXT_BTN_FALLBACKS = [
    'button:has-text("Next")',               # button text
    'button[type="button"]:visible',         # visible button
    'form button:first-of-type',             # first button in form
]
PASSWORD_FALLBACKS = [
    'input[type="password"]',                # type is unique per page
    'input[placeholder*="assword" i]',       # placeholder containing "password"
]
SIGN_IN_BTN_FALLBACKS = [
    'button:has-text("Sign In")',            # button text
    'button[type="submit"]',                 # submit button
    'form button:first-of-type',             # first button in form
]

# ── Main page ────────────────────────────────────────────────────
REPORTS_TAB_CSS = 'a[href="#/reports"]'

# Iframe identification — fast-path by name, fallback by content
REPORTS_IFRAME_NAME = 'remote_iframe_3'
REPORTS_IFRAME_CONTENT_MARKER = '.ngGrid'
IDENTITY_IFRAME_NAME = 'remote_iframe_0'
IDENTITY_IFRAME_CONTENT_MARKERS = [
    'div[id*="user"]',
    'button[id*="user"]',
    'a[id*="user"]',
]

# ── ng-grid (reports list) ───────────────────────────────────────
GRID_CONTAINER = '.ngGrid'
GRID_VIEWPORT = '.ngViewport'
GRID_ROW = '.ngRow'
NAME_CELL = '.name_cell_container.colt0'
NAME_TEXT = '.nameCell span.ellipsis, .nameCell span.ellipses'
FOLDER_ICON = '.icon.icon-folder'
REPORT_ICON = '.icon.icon-report'
