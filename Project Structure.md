# Modular Snapshot Scraper - Project Structure

## 📁 Directory Layout

```
/data_aggregator
│
├── driver.py                 # The Orchestrator - Runs all workers every 5 mins
├── base_worker.py            # BaseWorker class with login helpers & browser mgmt
├── common_utils.py           # CSV handling, snapshot logic, auto-documentation
├── requirements.txt          # Python dependencies
│
├── run_driver.bat            # Run the scraper (shows console output)
├── run_driver_silent.bat     # Run silently (for Task Scheduler)
│
├── /workers                  # Site-Specific Scrapers (Plugins)
│   ├── __init__.py           # Package initialization
│   ├── _example_worker.py    # Template worker (ignored by driver - starts with _)
│   ├── smax_worker.py        # [Example] SMAX ticket extraction
│   └── README.md             # Instructions for creating workers
│
├── /logs                     # Daily log files (auto-created)
│   └── driver_YYYYMMDD.log   # Log file for each day
│
├── /python_installer         # Portable Python Environment Setup
│   ├── install.bat           # Run this FIRST to set up Python
│   ├── setup_env.ps1         # PowerShell installer script
│   ├── requirements.txt      # Dependencies to install
│   └── /python_bin           # Portable Python (created by installer)
│
├── kpi_snapshots.csv         # OUTPUT: Main data file for Power BI
└── DATA_DICTIONARY.md        # AUTO-GENERATED: Schema documentation
```

---

## 🧠 Core Components

### 1. driver.py (The Orchestrator)

**Purpose:** Runs every 5 minutes via Task Scheduler

**Actions:**
- Scans `/workers` folder for Python modules
- Dynamically imports and executes each worker's `scrape()` function
- Handles failures individually (one crash doesn't stop others)
- Logs all activity to daily log files

**Error Handling:** If a worker fails, the driver logs the error and continues to the next worker.

---

### 2. base_worker.py (The Foundation)

**Purpose:** Abstract base class that all workers inherit from

**Provides:**
- Playwright browser setup (headless Chromium)
- Login helper methods (`login_with_form()`)
- Safe data extraction (`safe_get_text()`, `safe_get_number()`)
- Automatic cleanup of browser resources

**Usage:**
```python
from base_worker import BaseWorker

class Worker(BaseWorker):
    SOURCE_NAME = "my_source"
    
    def scrape(self):
        # Your logic here
        return {'my_source_total': 42}
```

---

### 3. common_utils.py (The Data Engine)

**Purpose:** Handles all data operations

**Features:**
- **Snapshot Logic (Idempotent):** Replaces data for current day, doesn't duplicate
- **Auto-Documentation:** Detects new columns and updates DATA_DICTIONARY.md
- **CSV Management:** Load, save, and clean up data

**Key Function:**
```python
process_worker_result(source_name, data)
# Handles everything: load CSV → update snapshot → save → document new columns
```

---

## 🔌 Creating a New Worker

1. **Copy the template:**
   ```
   Copy workers/_example_worker.py → workers/mysite_worker.py
   ```

2. **Update the class:**
   ```python
   class Worker(BaseWorker):
       SOURCE_NAME = "mysite"  # Unique identifier
       DESCRIPTION = "MyPortal ticket scraper"
       
       def scrape(self):
           # Login
           self.login_with_form(...)
           
           # Navigate & extract
           self.page.goto("https://mysite.com/dashboard")
           total = self.safe_get_number('.ticket-count')
           
           return {
               'mysite_total_tickets': total
           }
   ```

3. **Test independently:**
   ```batch
   python_installer\python_bin\python.exe workers\mysite_worker.py
   ```

4. **Done!** Driver will auto-detect on next run.

---

## ⚙️ Installation & Setup

### Step 1: Install Python Environment
```batch
cd python_installer
install.bat
```

This downloads portable Python 3.11 and installs:
- Playwright (headless browser)
- Pandas (data processing)
- Requests, urllib3

### Step 2: Test the Driver
```batch
run_driver.bat
```

### Step 3: Schedule with Task Scheduler
- Program: `C:\Dev\data_aggregator\run_driver_silent.bat`
- Trigger: Every 5 minutes
- Run whether user is logged on or not

---

## 📊 Data Logic: Snapshot Replacement

The system uses **idempotent snapshot logic** - it doesn't accumulate values:

| Time | Action |
|------|--------|
| 8:00 | First run → Create row: `date=2026-02-05, smax_tickets=100` |
| 8:05 | Second run → Update row: `smax_tickets=102` (replaced, not added) |
| 8:10 | Third run → Update row: `smax_tickets=105` |
| Next day | New row created for new date |

**Result:** CSV shows latest snapshot per day per source. No duplicates.

---

## 📝 Auto-Documentation

When a new KPI column appears, DATA_DICTIONARY.md is automatically updated:

```markdown
| Column Name | Source | Description | First Detected |
| :--- | :--- | :--- | :--- |
| smax_tickets | smax | KPI from smax worker. [Add description] | 2026-02-05 14:30:00 |
```

---

## 🔗 Power BI Connection

1. Move `kpi_snapshots.csv` to OneDrive/SharePoint synced folder
2. Update `DEFAULT_OUTPUT_DIR` in `common_utils.py`
3. In Power BI: Get Data → Web → OneDrive file URL
4. Team members can view without VPS access
