# CUIC Worker Package

This package contains the refactored CUIC (Cisco Unified Intelligence Center) worker, split into multiple modules for better organization and maintainability.

## Structure

```
workers/cuic/
├── __init__.py        # Main Worker class (entry point)
├── selectors.py       # CSS/XPath selectors
├── javascript.py      # JavaScript snippets for browser injection
├── auth.py            # Login and logout methods
├── navigation.py      # Reports navigation and grid helpers
├── wizard.py          # Wizard field reading and filter application
├── scraper.py         # Data scraping methods (ag-grid, DOM, HTML)
└── README.md          # This file
```

## Module Descriptions

### `__init__.py` - Main Worker Class
- Entry point for the worker
- Orchestrates all other modules
- Implements the `run()` and `scrape()` methods
- Inherits from `BaseWorker`

### `selectors.py` - Selectors
- Contains all CSS and XPath selectors used throughout the worker
- Centralized location for all DOM selectors

### `javascript.py` - JavaScript Snippets
- JavaScript code injected into the browser for:
  - Reading CUIC wizard fields (multi-step and SPAB)
  - Applying filter values via Angular scope manipulation
  - Scraping ag-grid data via internal API
  - Generic HTML form reading

### `auth.py` - Authentication
- `login(worker)` - 2-stage login (username → password + LDAP)
- `logout(worker)` - Sign out with multiple fallback strategies

### `navigation.py` - Navigation
- `get_reports_frame(worker)` - Access the reports iframe
- `open_report(worker, frame, folder_path, report_name)` - Navigate folder tree and click report
- `close_report_page(worker)` - Clean up extra browser tabs
- `navigate_to_reports_root(worker)` - Return to reports list
- Helper functions for ng-grid interaction

### `wizard.py` - Wizard Handling
- `read_wizard_step_fields(worker)` - Read current wizard step's fields
- `run_filter_wizard(worker, filters)` - Execute wizard with saved filter values
- `apply_filters_to_step(worker, step_info, saved_values)` - Apply filters to current step
- `discover_wizard(worker_class, report_config)` - Report discovery for settings UI
- Support for:
  - CUIC SPAB (single-step parameterized reports)
  - CUIC multi-step wizards (filter-wizard directive)
  - Generic HTML forms

### `scraper.py` - Data Scraping
- `scrape_data(worker, report_label)` - Main scraping entry point
- Multiple fallback strategies:
  1. **ag-grid JavaScript API** - Extracts ALL rows via grid's internal API (best)
  2. **ag-grid DOM scraping** - Scrapes visible rows from DOM (fallback)
  3. **Plain HTML tables** - Generic table scraping (last resort)

## Usage

The worker can be imported and used like any other worker:

```python
from workers.cuic import Worker

worker = Worker()
data = worker.run()
```

## Migration from `cuic_worker.py`

The original monolithic `cuic_worker.py` (~2500 lines) has been split into this organized package structure. All functionality remains the same, but the code is now:

- **More maintainable** - Each module has a single responsibility
- **Easier to navigate** - Related code is grouped together
- **More testable** - Individual modules can be tested in isolation
- **Better documented** - Each module has clear purpose and API

The original `cuic_worker.py` file has been preserved for reference but is no longer used.

## Settings

Settings are still configured in `config/settings.json` under the `cuic` key:

```json
{
  "cuic": {
    "enabled": true,
    "url": "https://your-cuic-server:8444/cuicui/Main.jsp",
    "timeout_nav_ms": 30000,
    "timeout_short_ms": 1500,
    "timeout_medium_ms": 2500,
    "timeout_long_ms": 8000,
    "reports": [
      {
        "label": "my_report",
        "folder": "Stock/CCE/CCE_AF_Historical",
        "name": "Report Name",
        "enabled": true,
        "data_type": "realtime",
        "filters": {
          "step_1": {"DateTime": "THISDAY"},
          "step_2": {"CallTypeID": "all"}
        }
      }
    ]
  }
}
```

Credentials are in `config/credentials.json`:

```json
{
  "cuic": {
    "username": "your_username",
    "password": "your_password"
  }
}
```
