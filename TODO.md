# TODO

Pending work, backlog, and known issues.
Move items to `CHANGELOG.md` when completed.

---

## In Progress

1. **Debugging: Open Playwright Browser in Maximized/Full Screen Mode**

There's something that bothers me a lot. When I set the hit list mode to off to see what's happening in the automation, the browser opens in a very weird window size.

When I enlarge it, the website itself is still stuck to some sort of scale that is chopped off from the bottom right. I cannot see everything. Even if I try to scroll within that page, I couldn't.

It's like it's stuck, even if I maximize the window. So why don't you just open the web browser of the automation in full mode automatically whenever it runs? This way, I cannot debug correctly. It's very hard for me to debug.

2. **Data Consistency: Add Report Identifier & Replace Outdated Data on Scrape**

We have some reports that we are scrubbing the data from. So those reports have some filter settings. Whether you want the report of today, whether you want the report of yesterday, whether you want the report of a very specific time interval of a day. You can do that in the filter settings.

And we have this in our interface, the settings interface. So you can just add the report path, validate it, and it will show you the available settings that you can set from our interface, the settings. And it will be applied in the website side itself. Okay. So, by the way, this has some issue.

It's not applying the settings correctly. So we need to work on it. But the thing that I want to talk about right now, what if at some point we wanted to change the filter settings? Of course, the data that is coming from this report, the report will change eventually.

Right? So what about the data that already existing in the database that is from the same source, this report? This can create confusion. Okay. You are getting data from reports. You are just dumping them in the database, then dumping them in the CSV file without any identifier from where did this come.

Okay. We are not replacing the data when we got new data. We are adding on top of it. We are adding them beneath the file. We are just adding.

We are not replacing. So if at some point we change the settings of a filter, it should replace all the data that came from that report. So we need an identifier for each report. So each time or any time this report brings data or generated data, it will replace the old ones, all of them.

For example, if we have 100 rows of data that existing on our database and we got only 50 from the new scrap, replace all the 100 with the 50. This way we can ensure data consistency and the integrity of data. They are getting the data that they want without any irrelevant data that they didn't want.

And regarding if they want to get two different type of data from the same source, they can add it twice. They can add the report twice, each with different settings.

2. **Bug/Refactor: Filter Wizard Settings Not Applying Correctly in CUIC**

Speaking about the filter settings, we have something in our front-end, in the settings front-end, we have something called filter wizard settings. So when you provide a path of a report, and I'm talking about the worker CUIC, okay, it's trying to get the filters from the actual front-end, from the actual website, and giving them here in our website front-end, okay.

This will allow the user to just provide these settings, and he can just pre-select the settings that they want, instead of every time reselecting them, because when you select the filter settings, and you close that report, and you try to open it again, it will ask you to enter the settings again.

So without this feature of pre-selecting the settings themselves, we cannot scrub the data whenever we want, or we schedule scrubbing data. So this need to work correctly, and unfortunately, it does not work correctly. It has some issues. It does apply some settings correctly, but some settings like, if you want to get some specific time of the day, it's not applying.

For example, I have put that I want the data of yesterday, and I want the data to be from 10 a.m. to 12 p.m. It did select it correctly. I saw it in the UI, and I was running on headless mode off, and it did select it, but it didn't apply to the report itself.

For example, while choosing the default data, and in some other kind of reports, it didn't apply the report settings correctly. For example, while choosing the call types, I think, it did add them twice. It did add those groups that it should add twice. And regarding the time, it didn't even select the time.

It just passes, and it didn't select it, and go to the next step. So this means that our code is not getting the data of filter settings or not getting the filter settings from CUIC dynamically. So if settings somehow changed in some reports, settings changed, and I mean by this, that each report has different settings, different criteria and settings.

Okay, we can set anything or different things. And if this change, our code or our settings scrapper unfortunately breaks, and this will cause us a lot of problems. We want it to work dynamically. So we want to figure out how can we solve this issue.

What is the best solution for this and whether what we are doing is correct or it's over complicated. Let's just study what we can do here. 

## Backlog

_No open items currently tracked._

---

## Won't Fix / Out of Scope

_Nothing filed here yet._

---

## Notes & Future Ideas

- Power BI direct connector (REST) instead of CSV export
- Worker health dashboard showing per-report last-scraped time and row count
- E-mail or Teams alert when a worker fails consecutively
- Support for additional BI platforms beyond CUIC and SMAX
- Scheduled re-validation of saved report links (detect URL rot)
