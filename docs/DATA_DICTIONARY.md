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
| **CUIC_% Aban** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_% Queued** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Abandoned** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Abandoned Within Service Level** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Answer Wait Time** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Answered** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Assigned From Queue** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Average Abandon Delay** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Avg Speed of Answer** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Calls Error** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_DateTime** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Default_Treatment** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Flow Out** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Handled** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Longest Queued** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Max Queued** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Network Routed** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Offered** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Other** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Return** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Service Level** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **CUIC_Short Calls** | cuic | Report from cuic. [Add description] | 2026-02-09 10:47:39 |
| **Unknown Report** | smax | Report from smax. [Add description] | 2026-03-22 19:56:02 |
| **CUIC_%Active** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_%Hold** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_%Not Active** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_%Not Ready** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_%Reserved** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_%Wrap Up** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_Abandon Hold** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_Abandon Rings** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_Agent Terminated Calls** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_Avg Handle Time** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_Avg Hold Time** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_External Out** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_FullName** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_Held** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_Logged On Time** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_Media** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_RONA** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_Transfer In ** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_Transfer Out ** | cuic | Report from cuic. [Add description] | 2026-04-03 16:33:29 |
| **CUIC_%Busy Other** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_%Hold Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_%Wrapup** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Abandon Ring** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Abandon Ring Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Agent** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Agent Available Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Agent Busy Other Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Agent Logged On Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Agent Not Ready** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Agent Out Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Agent Out Calls On Hold** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Agent Out Calls On Hold Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Agent Out Calls Talk Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Agent Skill Target ID** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Auto Out** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Auto Out On Hold** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Auto Out On Hold Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Auto Out Talk Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Auto Out Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Barge In Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Callback Messages** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Callback Messages Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Conference In Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Conference Out Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Conferenced In Calls Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Conferenced Out Calls Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Consults** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Consults Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Database DateTime** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Emergency Assists** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Handle Talk Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Handle Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Hold Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Inbound On Hold** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Inbound On Hold Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Intercept** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Internal** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Internal On Hold** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Internal On Hold Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Internal Received** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Internal Received Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Internal Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Interrupted Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Interval** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Media ID** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Monitor Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Network Conferenced Out Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Network Conferenced Out Calls Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Network Consultative Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Network Consultative Calls Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Network Transferred Out Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Out Extension Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Preview Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Preview Calls On Hold** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Preview Calls On Hold Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Preview Calls Talk Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Preview Calls Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Redirect** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Redirect Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Reservation Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Reservation Calls On Hold** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Reservation Calls On Hold Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Reservation Calls Talk Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Reservation Calls Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Reserved Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Skill Group ID** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Skill Group Name** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Supervisor Assist** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Supervisor Assist Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Talk Auto Out Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Talk Other Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Talk Out Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Talk Preview Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Talk Reserve Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Talk Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Time Zone** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Transfer In** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Transfer In Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Transfer Out** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Whisper Calls** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Work Ready Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_Wrap Up Time** | cuic | Report from cuic. [Add description] | 2026-04-05 11:32:00 |
| **CUIC_%Active Time** | cuic | Report from cuic. [Add description] | 2026-04-05 13:21:04 |
