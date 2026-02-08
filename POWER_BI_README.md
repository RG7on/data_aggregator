# Power BI Setup Guide

## 1. Connect to Data Source
In Power BI Desktop:
1. Click **Get Data** -> **Text/CSV**.
2. Select the file: `c:\Dev\data_aggregator\kpi_snapshots.csv`.
3. Click **Load**.

## 2. Modeling the Data
The data is in a "Long Format" (normalized), meaning all different reports are stacked in one big table. You do not get separate columns for each KPI. Instead, you filter.

### Critical Columns:
*   **Metric Title**: The name of the report (e.g., "Aging Requests"). **You MUST filter your visuals by this column.**
*   **Category**: The main label for the data row (e.g., "Feb 2026", "Open", "true").
*   **Sub Category**: Use this for complex tables (like "First line support" vs "Review").
*   **Value**: The actual number to sum or average.
*   **Date**: The date the snapshot was taken. Use this for the X-axis on trend charts.

## 3. Creating Visuals (Examples)

### **Example A: Trend Chart for "Aging Requests"**
1. Create a **Line Chart**.
2. **X-Axis**: Drag `date` here.
3. **Y-Axis**: Drag `value` here (set to Sum).
4. **Legend**: Drag `category` (Month) or `sub_category` (Phase).
5. **Filters on this visual**:
   *   Drag `metric_title` to filters and select **"Aging Requests"**.
   *   Drag `category` to filters and **uncheck "total"** (to avoid double counting).

### **Example B: Correct/Incorrect Pie Chart**
1. Create a **Pie Chart**.
2. **Legend**: Drag `category` (stores 'true'/'false').
3. **Values**: Drag `value`.
4. **Filters on this visual**:
   *   Drag `metric_title` to filters and select **"ISC: First Touch Response <1 hour"**.
   *   Filter `category` to exclude "total".

---
**Note:** Always exclude the `category` = "total" row unless you are making a single "KPI Card" visual. The scraper captures the total separately for convenient card displays.
