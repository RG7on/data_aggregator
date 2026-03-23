## these problems need to be fixed

### ✅ FIXED — Issue 1: about:blank tabs visible during scraping

**Status**: RESOLVED  
**Files Changed**: `workers/smax_worker.py`

When opening multiple report tabs, blank tabs were visible for ~2 seconds before navigation due to incorrect event ordering. Fixed by reordering the stagger delay to occur **before** `context.new_page()` is called, so the blank tab exists for near-zero time.

---

1. ~~We have a problem. It's not affecting the process itself and causing it to fail, but it's good if we address it. So the issue is that when I run the scrabber in any way, whether I'm validating a link in SMAX, whether I am running the scrabber itself, it's going to open up some tabs, right, regarding what you are going to do. For example, if you want to validate a link, it will open a tab trying to validate a link and follow the process that it have set to do. But the thing here that it's opening a blank tab. I don't know why, but it's opening a blank tab always, whether I am validating a link or scrubbing a web page itself, it's opening a blank. I don't know why, but it's bothers me and it will be good if we address it. (about:blank)~~

---

---

### ⏸️ POSTPONED — Issue 3: Settings UI/UX redesign

**Status**: DEFERRED (handle together with Issue 3)  
**Timeline**: To be completed as part of comprehensive control panel UI/UX overhaul

> One thing that angsts me about our system is the settings UI. So it's not only the settings UI, it's our, like, our service control panel itself. We are firing or starting scraping from there. We are seeing the scraping status from there. We are seeing everything. It's not only for settings. We will change its name sooner or later, but I don't like its UI. It's stupid. It's also hard to use. It's not organized in a way that it should be organized. [...] We need to revamp the whole thing and make it more usable, more user-friendly, and its UX and UI far more better than this.

**Action**: This is a scope-2 redesign that requires comprehensive UX planning and will be tackled together with other UI improvements in a dedicated pass

**Status**: RESOLVED  
**Files Changed**: `workers/smax_worker.py`, `core/database.py`

**Root Causes**:
- Worker caught exceptions internally but never called `log_scrape()` — no history entries for worker-level errors
- `has_historical_data()` was fundamentally broken: queried `kpi_snapshots.metric_title` (DOM page title) against config `label` string — they never matched, so historical skips never fired for any worker

**Fixes**:
1. Added `log_scrape()` calls to the `run()` exception handler and early-return path in `smax_worker.py`
2. Completely rewrote `has_historical_data()` to query **only `scrape_log`** using the config `label`, which is consistent and reliable
---

---

### ✅ FIXED — Issue 5: "Unknown Report" rows with zero total

**Status**: RESOLVED  
**Files Changed**: `workers/smax_worker.py`, `core/database.py`

**Root Cause**: When a report page fails to load (missing DOM title element but partial data), rows were written to the database with `metric_title = "Unknown Report"`, making them unqueryable in Power BI. Additionally, old rows from failed scrapes accumulated over time.

**Fixes**:
1. **Added label fallback** in `_extract_from_page()`: When the DOM title element is missing, the config `label` is now used as the `metric_title` instead of the generic `"Unknown Report"` string
2. **One-time cleanup** in `init_db()`: Executes `DELETE FROM kpi_snapshots WHERE metric_title = 'Unknown Report'` on startup to remove stale rows from earlier runs (idempotent and safe)

Now all report rows are properly identified and queryable in Power BI, and the database stays clean.

---

5. ~~There is also another thing that I want to highlight. I don't know whether we can consider it as a problem or it's just an anomaly, a small anomaly. But for example, I was previously, I was trying to scrub a report and there was a problem in the scraper where it's not scraping data correctly. [...] the report itself, it's written here, unknown report, and the type of data or the thing that it's trying to pull, which is the total, is set as zero. [...] So should we just ignore it or we can do something about it, or what exactly?~~

**Status**: RESOLVED  
**Files Changed**: `workers/smax_worker.py`, `workers/cuic/__init__.py`, `config/settings.json`, `core/database.py`

**Root Causes**:
- The `has_historical_data()` function was completely broken (fixed in Issue 2), so historical skip logic never fired
- The `aging_requests` SMAX report was manually misconfigured as `"ongoing"` despite its filter clearly showing `"Past year"`
- No automatic period detection existed — all classification required manual config editing

**Fixes**:
1. **Fixed `has_historical_data()`** (see Issue 2)
2. **Auto-detection added** for both SMAX and CUIC:
   - **SMAX**: Scans `properties.filters[*].display_value` for: *past year, previous year, last year, previous month, past month, last month, previous week, past week, last week, previous quarter*
   - **CUIC**: Scans `filters._meta.steps[*].params[*].relativeRange/currentPreset` for: `LASTYR`, `LASTMTH`, `LASTWK`, `LASTQTR`
   - Auto-detection **only fires when `data_type` is absent** — explicit config settings are always respected (non-breaking)
3. **Updated `aging_requests`** in settings.json: changed `data_type` from `"ongoing"` → `"historical"`

Now the system correctly identifies historical reports and skips re-scraping them on subsequent runs.

---

4. ~~We have another issue, and it's regarding the ability for our service to identify whether the data is historical or it's ongoing data. [...] There are historical data, there are ongoing data. [...] The thing is, there are one type of report I am pulling from SMS, and it's clearly saying that it's last year. And still our service or our code considering it like ongoing data. So we need to make sure that it identifies the data or classifies the data correctly, whether they are historical or ongoing data for all the websites we are scrabig from.~~
Now SMAX (and CUIC) scrape history appears correctly in `/api/scrape-log` endpoint and the dashboard.

---

2. ~~We have another issue. It's also not affecting the process itself, but it's considered to be missing. So when you perform any type of scrape, whether it's Testmax or CUIU website, it's going to be shown in the history in the dashboard itself, the scrape history. I've noticed that when I scrape in Testmax, it doesn't show there. It doesn't show in the history itself. So this needs to be addressed.~~

3. One thing that angsts me about our system is the settings UI. So it's not only the settings UI, it's our, like, our service control panel itself. We are firing or starting scraping from there. We are seeing the scraping status from there. We are seeing everything. It's not only for settings. We will change its name sooner or later, but I don't like its UI. It's stupid. It's also hard to use. It's not organized in a way that it should be organized. So we need to work on it. We need first to study it and actually see what do we have, what also we could be adding in the future to make it ready to handle it, or we can just add it to our updated UI set that we are going to create later on. So it's not only the UI we are talking here, we are also talking about the user experience. We are talking in terms of UI and UX. What is also make me anxious that I need to save every time I change settings. Maybe you can do something about this where settings is being saved automatically instead me go and save it manually because it's um It's make me anxious and it's not a very good UI. As I told you, we need to revamp the whole thing and make it more usable, more user-friendly, and its UX and UI far more better than this. We can do better. I'm not talking about something extraordinary, but I'm talking about something actually feels like a real service to use, not some gimmick or thing that feels it will break easily, you know.

4. We have another issue, and it's regarding the ability for our service to identify whether the data is historical or it's ongoing data. So as you can see, we have two types of data. We have classified data into two types. There are historical data, there are ongoing data. And the thing behind this is that we have two types of data, data that are not changing. They are closed. So for example, you are getting last or past week data. Past week data is not going to change. It will stay the same and it will not change. So identifying it as historical data or classifying it as historical data will allow our code to, it will avoid scrubbing it again and again and again. So if it is historical data, it will not scrub it again later. It will only scrub ongoing data, the data that are changing, data like today's data, data like this week data. The week is not over, so it's keep scrubbing this week data, the ongoing data, this month, this year data. Things that are from the past are historical, like past year, past month, past week, for example. Those kind of things that are considered to be historical. The thing is, there are one type of report I am pulling from SMS, and it's clearly saying that it's last year. And still our service or our code considering it like ongoing data. So we need to make sure that it identifies the data or classifies the data correctly, whether they are historical or ongoing data for all the websites we are scrabig from.

5. There is also another thing that I want to highlight. I don't know whether we can consider it as a problem or it's just an anomaly, a small anomaly. But for example, I was previously, I was trying to scrub a report and there was a problem in the scraper where it's not scraping data correctly. And it scrapes one row of data. It got everything correctly, like the date when it scraped it, what is the source of it, but the report itself, it's written here, unknown report, and the type of data or the thing that it's trying to pull, which is the total, is set as zero. So this line of data is not significant for us. We are not using it. I don't know whether this is, I think it is correct, like it's identified that it's unknown report and the total is zero and so on. So I don't know whether this will make us trouble later or make us problems, or we can just keep it as long as it has been classified as unknown report, and as long as we have the correct data written, like the name of the report and what we are trying to pull from there exactly, we can just pull or choose them selectively in the place we are going to represent those data on, which is PowerBI. So should we just ignore it or we can do something about it, or what exactly? I must have highlighted this, if it will be making any issues, we can address it. If not, we can just ignore it.

