# Project Conventions

Rules for structure, naming, and development in this repository.
Read this before adding files, folders, or new workers.

---

## 1. Folder Structure

```
data_aggregator/
├── config/           Runtime configuration (settings, credentials, Chrome profile)
├── core/             Framework: base class, config loader, database, orchestrator
├── workers/          Pluggable scraper modules — one file or one package per source
├── ui/               Browser-based control panel (HTML/CSS/JS — no build tools)
├── scripts/          Windows batch/PowerShell launchers (Task Scheduler, manual run)
├── docs/             Human-readable documentation
│   └── reference/    Raw HTML DOM snapshots used for selector development
├── output/           Runtime output: kpi_snapshots.csv (auto-created, not committed)
├── logs/             Daily rotating log files (auto-created, not committed)
├── python_installer/ Portable Python 3.11 installation (one-time setup)
├── run.py            Entry point
├── settings_server.py Control panel HTTP server (port 8580)
├── CHANGELOG.md      Log of all completed changes
└── TODO.md           Pending work and backlog
```

### Rules
- **Do not put scripts at the root.** Batch/PowerShell launchers go in `scripts/`.
- **Do not put documentation at the root.** Markdown docs go in `docs/`.
- **Do not put HTML snapshots directly in `docs/`.** DOM debug files go in `docs/reference/`.
- **Do not commit runtime artifacts.** `output/`, `logs/`, `output/*.db`, `config/credentials.json`, and `config/smax_chrome_profile/` are all excluded by `.gitignore`.
- **Do not commit junk.** `.bak` files, `tmpclaude-*` folders, `__pycache__/`, and Playwright output directories must never be committed. They are blocked in `.gitignore`.

---

## 2. Naming Rules

### Python files
| Pattern | Meaning |
|---------|---------|
| `workers/my_source_worker.py` | Single-file worker module |
| `workers/my_source/` | Multi-file worker package (preferred when > ~200 lines) |
| `workers/_name.py` | Ignored by the driver — templates, backups, experiments |
| `core/verb_noun.py` | Framework utility (e.g. `base_worker.py`, `common_utils.py`) |

### Config keys
- Worker settings live under `settings.json["workers"]["worker_name"]`
- Worker credentials live under `credentials.json["worker_name"]`
- The `worker_name` key must match the directory/module name exactly

### Markdown docs
| File | Purpose |
|------|---------|
| `CHANGELOG.md` | Every completed change. One entry per logical change. |
| `TODO.md` | Pending work, backlog, future ideas |
| `docs/CONVENTIONS.md` | This file |
| `docs/Project Structure.md` | Annotated folder tree (keep in sync with reality) |
| `docs/DATA_DICTIONARY.md` | Auto-generated — do not edit by hand |
| `docs/POWER_BI_README.md` | Power BI integration guide |
| `docs/reference/*.html` | DOM snapshots for selector development |

---

## 3. Adding a New Worker

### Step 1 — Choose single-file or package
- **Single file** (`workers/my_worker.py`): fine for simple sources with < ~200 lines
- **Package** (`workers/my_source/`): use when you have auth, navigation, scraping, and JS snippets as distinct concerns (see `workers/cuic/` as the reference implementation)

### Step 2 — Implement the Worker class

```python
# workers/my_worker.py
from core.base_worker import BaseWorker

class Worker(BaseWorker):
    NAME = "my_worker"          # Must match the config key in settings.json

    def scrape(self) -> list[dict]:
        """
        Returns a list of dicts, each with:
          metric_title  — report/widget name (str)
          category      — primary dimension value (str)
          sub_category  — secondary dimension value (str, may be empty)
          value         — the numeric or string KPI value (str)
        """
        ...
```

The class **must** be named `Worker`. The driver discovers it by this name.

### Step 3 — Add config & credentials

In `config/settings.json`:
```json
"workers": {
  "my_worker": {
    "enabled": true,
    "reports": [...]
  }
}
```

In `config/credentials.json`:
```json
{
  "my_worker": {
    "username": "...",
    "password": "..."
  }
}
```

### Step 4 — Use `BaseWorker` helpers

`BaseWorker` provides:
- `self.settings` — your worker's config block from `settings.json`
- `self.credentials` — your worker's credentials block
- `self.logger` — pre-configured logger (writes to `logs/`)
- `setup_browser() / teardown_browser()` — Playwright browser lifecycle
- `login_with_form(url, user_sel, pass_sel, submit_sel)` — generic form login

### Step 5 — Test manually

```bash
python run.py
```

The driver auto-discovers any `workers/*.py` or `workers/*/` package with a `Worker` class.

### Step 6 — Document
- Add an entry to `CHANGELOG.md` under a new date heading
- Update `docs/Project Structure.md` with the new worker

---

## 4. Config Conventions

| Rule | Detail |
|------|--------|
| `settings.json` is version-controlled | Safe to commit — contains no secrets |
| `credentials.json` is git-ignored | Never commit it; provision manually on each host |
| Use `get_worker_settings(name)` | Returns `settings["workers"][name]`; always use this accessor |
| Use `get_worker_credentials(name)` | Returns `credentials[name]`; always use this accessor |
| Call `config.reload()` after UI saves | The HTTP API in `settings_server.py` calls this automatically |
| Chrome profiles stay in `config/` | `config/smax_chrome_profile/` — git-ignored, never commit |

---

## 5. What Must Never Be Committed

These are blocked by `.gitignore`. If you find them in a branch or PR, remove them.

| Item | Reason |
|------|--------|
| `config/credentials.json` | Contains plaintext passwords |
| `config/smax_chrome_profile/` | Contains browser session cookies |
| `output/*.db` | SQLite runtime database — rebuilt on startup |
| `logs/` | Runtime log files |
| `__pycache__/`, `*.pyc` | Python bytecode cache |
| `*.bak` | Backup files — use version control instead |
| `tmpclaude-*` | Claude CLI temp folders |
| `CDevdata_aggregator*` | Playwright debug output directories |
| `.venv/`, `venv/` | Virtual environments |

---

## 6. Python Style

This project uses the Python style already established in `core/` and `workers/`. Follow these conventions:

- **Python 3.11+** — use modern syntax (`match`, `|` union types, `list[str]` annotations)
- **Synchronous Playwright** — use `sync_playwright`, not `async`. The driver is single-threaded.
- **Logging** — use `self.logger` (from `BaseWorker`), never `print()` in production code
- **No external dependencies without approval** — check `requirements.txt` before importing something new
- **Selectors** — centralize in a `selectors.py` file for any package with more than ~5 selectors. Order: `data-*` attributes > ARIA roles/labels > text content > CSS class > XPath
- **No hardcoded credentials** — always read from `core.config.get_worker_credentials()`

---

## 7. Keeping This Document Up to Date

When you make a structural change (new folder, renamed module, changed convention):
1. Update `docs/CONVENTIONS.md` in the same commit
2. Update `docs/Project Structure.md` if the folder tree changed
3. Add an entry to `CHANGELOG.md`
