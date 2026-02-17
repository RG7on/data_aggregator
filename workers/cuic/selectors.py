"""
CUIC Selectors
==============
CSS and XPath selectors used throughout the CUIC worker.
"""

# ── Login ─────────────────────────────────────────────────────────
USERNAME_XPATH = 'xpath=/html/body/form/div/div/div/div/div[1]/div[3]/input[1]'
NEXT_BTN_XPATH = 'xpath=/html/body/form/div/div/div/div/div[2]/button[1]'
PASSWORD_XPATH = 'xpath=/html/body/form/div/div/div/div/div[1]/div[2]/input[2]'
DOMAIN_SELECT_XPATH = 'xpath=/html/body/form/div/div/div/div/div[1]/div[3]/select'
SIGN_IN_BTN_XPATH = 'xpath=/html/body/form/div/div/div/div/div[2]/button[1]'

# ── Main page ─────────────────────────────────────────────────────
REPORTS_TAB_CSS = 'a[href="#/reports"]'
REPORTS_IFRAME_NAME = 'remote_iframe_3'

# ── ng-grid (reports list) ────────────────────────────────────────
GRID_CONTAINER = '.ngGrid'
GRID_VIEWPORT = '.ngViewport'
GRID_ROW = '.ngRow'
NAME_CELL = '.name_cell_container.colt0'
NAME_TEXT = '.nameCell span.ellipsis, .nameCell span.ellipses'
FOLDER_ICON = '.icon.icon-folder'
REPORT_ICON = '.icon.icon-report'
