# TODO

Pending work, backlog, and known issues.
Move items to `CHANGELOG.md` when completed.

---

## In Progress
1. CUIC worker as almost working correctly (logging in, navigating to report, settings wizard, but not yet extracting the data), we need to read the data from the web page and save it to a CSV file. the report can have alot of fealds and rows, lets give the user the option to select which fealds they want to extract and whether to extract all rows or only the consaledated ones, for example look at (docs\reference\Z Call Type Historical All Fields-Call Type Historical All Fields.csv) you will see groups like General_IT_CT line NO 19, RTPS_CT line NO 23, Subsurface_CT line NO 40. these groups have a lot of rows, but they are consaledated, so we can give the user the option to extract only the consaledated rows for these groups, or to extract all rows for these groups, and for other fealds that dont have consaledated rows we can just extract all rows. this will help reduce the amount of data extracted and make it more manageable for the user. but by defult only get the consaledated ones and the global consaledated row the one you can see at the end of the report, see line NO 48 in (docs\reference\Z Call Type Historical All Fields-Call Type Historical All Fields.csv).

we need to study the how can we extract the data from the web page robustly and in a way that it less likly to break. and it works for all reports, not just the one we are testing with.

we need to also update the settings accordingly to allow the user to select which fealds they want to extract and whether to extract all rows or only the consaledated ones for the groups that have consaledated rows.

2. studing if the curunt CSV file that suppose to store evrything can holdup or we need to change the way we store the data ?

3. we bring clomns and rows slection to SMAX worker as well, and we need to study how to do that in a way that is user friendly and easy to use.


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
