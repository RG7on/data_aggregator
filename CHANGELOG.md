# Changelog

All notable changes to this project are documented here.
Format: each entry has a **date**, **summary**, **files changed**, and **root cause / fix** where relevant.

---

## [2026-03-30] — Codebase Organization & Project Conventions

### Added
- `CHANGELOG.md` — this file; tracks all completed changes going forward
- `TODO.md` — structured backlog for pending and future work
- `docs/CONVENTIONS.md` — project-wide rules for folder structure, naming, and adding workers
- `docs/reference/` — subfolder for HTML DOM snapshots used during selector development

### Changed
- `docs/` root cleaned up: all HTML snapshots moved to `docs/reference/`
- `docs/Project Structure.md` updated to reflect current layout

### Removed
- `tmpclaude-*-cwd/` folders — Claude CLI temp artifacts (4 folders)
- `CDevdata_aggregatorplaywright_output/` — misplaced Playwright test output folder
- `ui/settings.html.bak` — superseded by the multi-file UI redesign
- `workers/_cuic_worker_backup.py` — old monolithic CUIC file, fully replaced by `workers/cuic/` package
- `docs/need to be fixed/` — raw issue-tracking folder, migrated into `CHANGELOG.md` + `TODO.md`

### Updated `.gitignore`
- Added `tmpclaude-*/` to prevent future Claude CLI temp folders
- Added `output/*.db` for SQLite runtime database
- Added `CDevdata_aggregator*/` for misnamed Playwright output directories
- Added `*.bak` to block backup file commits

---

## [2026-03] — UI Redesign: Settings → Control Panel

**Files changed:** `ui/index.html`, `ui/css/main.css`, `ui/js/app.js`, `ui/js/settings-io.js`, `ui/js/dashboard.js`, `ui/js/cuic.js`, `ui/js/smax.js`, `settings_server.py`

Replaced the monolithic `settings.html` (2586 lines) with a fully redesigned multi-file control panel.

**What was done:**
- Dark mode OLED design system (`#020617` base, `#0f172a`/`#1e293b` surfaces, `#3b82f6` accent)
- Sidebar navigation with 5 pages: Dashboard, Global, CUIC, SMAX, Export
- Auto-save with 1.5 s debounce — no manual save button required
- CUIC and SMAX connection settings merged with their report lists on the same page
- Full Filter Wizard UI for CUIC reports (multistep, SPAB, generic)
- SMAX properties discovery panel
- Dashboard with live scrape stats, status cards, manual scrape trigger, and scrape history log
- Export/Import page for settings and credentials JSON
- Pure CSS design system — no build tools, no CDN dependencies (corporate-network safe)
- `settings_server.py` updated to serve `/css/*` and `/js/*` static routes

---

## [2026-03] — Fix: SMAX Scrape History Not Shown in Dashboard

**Files changed:** `workers/smax_worker.py`, `core/database.py`

**Root causes:**
- Worker caught exceptions internally but never called `log_scrape()` — no history entries for worker-level errors
- `has_historical_data()` queried `kpi_snapshots.metric_title` (DOM page title) against config `label` string — they never matched, so historical skips never fired

**Fixes:**
1. Added `log_scrape()` calls to the `run()` exception handler and early-return path in `smax_worker.py`
2. Rewrote `has_historical_data()` to query only `scrape_log` using the config `label`, which is always consistent

---

## [2026-03] — Fix: Historical vs. Ongoing Data Classification

**Files changed:** `workers/smax_worker.py`, `workers/cuic/__init__.py`, `config/settings.json`, `core/database.py`

**Root causes:**
- `has_historical_data()` was broken (see above)
- `aging_requests` SMAX report was manually misconfigured as `"ongoing"` despite its filter showing `"Past year"`
- No automatic period detection existed

**Fixes:**
1. Fixed `has_historical_data()` (see above)
2. Added auto-detection for both SMAX and CUIC:
   - **SMAX**: Scans `properties.filters[*].display_value` for: past year, previous year, last year, previous month, past month, last month, previous week, past week, last week, previous quarter
   - **CUIC**: Scans `filters._meta.steps[*].params[*].relativeRange/currentPreset` for: `LASTYR`, `LASTMTH`, `LASTWK`, `LASTQTR`
   - Auto-detection only fires when `data_type` is absent in config — explicit settings are always respected (non-breaking)
3. Updated `aging_requests` in `settings.json`: changed `data_type` from `"ongoing"` → `"historical"`

---

## [2026-03] — Fix: "Unknown Report" Rows Written to Database

**Files changed:** `workers/smax_worker.py`, `core/database.py`

**Root cause:** When a report page fails to load (DOM title element missing), rows were written with `metric_title = "Unknown Report"`, making them unqueryable in Power BI.

**Fixes:**
1. Added label fallback in `_extract_from_page()`: when the DOM title element is missing, the config `label` is used as `metric_title` instead of the generic string
2. Added one-time cleanup in `init_db()`: executes `DELETE FROM kpi_snapshots WHERE metric_title = 'Unknown Report'` on startup (idempotent)

---

## [2026-03] — Fix: Blank `about:blank` Tab on Every Browser Launch

**Files changed:** `workers/smax_worker.py`

**Root cause:** When opening multiple report tabs, blank tabs were visible for ~2 seconds before navigation due to incorrect event ordering — the stagger delay happened after `context.new_page()`.

**Fix:** Moved the stagger delay to occur before `context.new_page()`, so the blank tab exists for near-zero time.

---

## [2026-03] — Refactor: CUIC Worker Split into Package

**Files changed:** `workers/cuic/` (new package), `workers/_cuic_worker_backup.py` (archived)

Split the monolithic CUIC worker into a clean 6-module package:
- `auth.py` — login/logout
- `navigation.py` — report folder navigation
- `wizard.py` — filter wizard reading and application
- `scraper.py` — data extraction (ag-grid JS API → DOM → HTML table fallback)
- `javascript.py` — browser JS snippets
- `selectors.py` — centralized DOM selectors
