# Data Dictionary
## KPI Snapshots Schema Documentation

This file is **automatically generated** by the Snapshot Scraper system.
New metrics are documented here as they are detected.

### 📊 How to use in Power BI
When creating visuals, you must filter by **Metric Title**.
Use the table below to find the exact name of the metric you want to display.

### CSV Structure
| Column | Description |
| :--- | :--- |
| date | The date of the snapshot (YYYY-MM-DD) |
| timestamp | Last update timestamp for the row |
| source | Identifier of the data source/worker |
| metric_title | Name of the report/metric being tracked |
| category | Primary grouping (e.g., 'Feb 2026', 'Close', 'true') |
| sub_category | Secondary grouping when table has 3+ columns (e.g., 'First line support') |
| value | The numeric value (count or percentage) |

---

### Tracked Metrics

| Metric Title | Source | Description | First Detected |
| :--- | :--- | :--- | :--- |
| **Aging Requests** | smax | Backlog aging summary (Month + Phase) | 2026-02-08 11:53:32 |
| **BIA Requests** | smax | Business Impact Analysis requests by status | 2026-02-08 11:40:15 |
| **ISC: First Touch Response <1 hour** | smax | Compliance percentage (True/False) | 2026-02-08 11:40:15 |
| **SLA -FCR This Month - 80% - Incident Excluded** | smax | First Contact Resolution stats | 2026-02-08 11:40:15 |
