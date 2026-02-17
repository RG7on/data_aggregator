# Data Aggregator — Project Structure

```
data_aggregator/
│
├── run.py                      # Entry point — runs all enabled workers
│
├── config/
│   ├── settings.json           # All settings (global + per-worker)
│   └── credentials.json        # Usernames & passwords (git-ignored)
│
├── core/
│   ├── __init__.py
│   ├── config.py               # Settings/credentials loader with caching
│   ├── base_worker.py          # Base class all workers inherit from
│   ├── common_utils.py         # Shared helpers (CSV merge, pivot, data dict)
│   └── driver.py               # Discovers & runs workers, orchestrates pipeline
│
├── workers/
│   ├── __init__.py
│   ├── cuic/                   # CUIC (Cisco) report scraper package
│   │   ├── __init__.py         # Main Worker class
│   │   ├── auth.py             # Login/logout
│   │   ├── navigation.py       # Report navigation
│   │   ├── wizard.py           # Filter wizard handling
│   │   ├── scraper.py          # Data extraction
│   │   ├── javascript.py       # Browser JS snippets
│   │   ├── selectors.py        # DOM selectors
│   │   └── README.md           # Package documentation
│   ├── smax_worker.py          # SMAX dashboard scraper
│   ├── _example_worker.py      # Template for new workers
│   └── README.md               # How to add a new worker
│
├── ui/
│   └── settings.html           # Browser-based settings editor
│
├── scripts/
│   ├── run.bat                 # Run with console output
│   ├── run_silent.bat          # Run silently (Task Scheduler)
│   └── open_settings.bat       # Open settings page in browser
│
├── docs/
│   ├── DATA_DICTIONARY.md      # Auto-generated column reference
│   ├── POWER_BI_README.md      # Power BI integration guide
│   └── Project Structure.md    # This file
│
├── output/                     # Worker CSV output (auto-created)
├── logs/                       # Log files (auto-created)
│
├── python_installer/           # Portable Python 3.11 + packages
│   ├── install.bat
│   ├── install_browsers.bat
│   └── python_bin/
│
├── requirements.txt
└── .gitignore
```

## Quick Start

1. **Install:** Run `python_installer\install.bat` (one time)
2. **Configure:** Open `scripts\open_settings.bat` → edit settings → copy JSON into `config/`
3. **Run:** Double-click `scripts\run.bat` or schedule `scripts\run_silent.bat`

## Adding a Worker

See `workers/README.md`. Copy `_example_worker.py`, implement `scrape()`, and add a config section in `settings.json`.
