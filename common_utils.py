"""
Common Utilities for Modular Snapshot Scraper
==============================================
Handles CSV operations, snapshot logic, and automatic data dictionary generation.

Supports two data formats:
1. Wide format (legacy): One row per source per day, multiple KPI columns
2. Long format (new): Multiple rows per source, with Date/Source/Metric Title/Category/Value columns
"""

import os
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Set, Union
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('common_utils')

# Configuration - Update this path to your OneDrive/SharePoint synced folder
DEFAULT_OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILENAME = "kpi_snapshots.csv"
DATA_DICTIONARY_FILENAME = "DATA_DICTIONARY.md"

# Core columns for LONG format (new structure)
LONG_FORMAT_COLUMNS = ['date', 'timestamp', 'source', 'metric_title', 'category', 'sub_category', 'value']

# Core columns for WIDE format (legacy structure)
WIDE_FORMAT_COLUMNS = ['date', 'timestamp', 'source_name']



def get_output_path(filename: str, output_dir: str = None) -> str:
    """Get the full path for an output file."""
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    return os.path.join(output_dir, filename)


def load_or_create_csv(output_dir: str = None, use_long_format: bool = True) -> pd.DataFrame:
    """
    Load existing CSV or create a new one with base columns.
    
    Args:
        output_dir: Directory for CSV file
        use_long_format: If True, use Date/Source/Metric Title/Category/Value format
    
    Returns:
        pandas DataFrame with the appropriate columns
    """
    csv_path = get_output_path(CSV_FILENAME, output_dir)
    columns = LONG_FORMAT_COLUMNS if use_long_format else WIDE_FORMAT_COLUMNS
    
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            logger.info(f"Loaded existing CSV with {len(df)} rows")
            return df
        except Exception as e:
            logger.error(f"Error loading CSV: {e}")
            return pd.DataFrame(columns=columns)
    else:
        logger.info("Creating new CSV file")
        return pd.DataFrame(columns=columns)



def save_csv(df: pd.DataFrame, output_dir: str = None):
    """Save DataFrame to CSV file."""
    csv_path = get_output_path(CSV_FILENAME, output_dir)
    df.to_csv(csv_path, index=False)
    logger.info(f"Saved CSV to {csv_path}")


# ============================================================
# LONG FORMAT FUNCTIONS (New - Date/Source/Metric Title/Category/Value)
# ============================================================

def update_snapshot_long(
    df: pd.DataFrame,
    source_name: str,
    data: List[Dict[str, Any]],
    current_date: str = None
) -> pd.DataFrame:
    """
    Update or insert snapshot rows using LONG format (idempotent).
    
    Logic for each metric:
    - Look for row matching [date] AND [source] AND [metric_title] AND [category]
    - If found: Overwrite the value
    - If not found: Append a new row
    
    Args:
        df: Existing DataFrame
        source_name: Identifier for the data source (e.g., 'smax')
        data: List of dicts with keys: metric_title, category, value
        current_date: Date string (YYYY-MM-DD), defaults to today
        
    Returns:
        Updated DataFrame
    """
    if current_date is None:
        current_date = datetime.now().strftime('%Y-%m-%d')
    
    current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Ensure all required columns exist
    for col in LONG_FORMAT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    
    for item in data:
        metric_title = item.get('metric_title', '')
        category = item.get('category', '')
        sub_category = item.get('sub_category', '')
        value = item.get('value', 0)
        
        # Check if row exists for this date/source/metric/category/sub_category combo
        mask = (
            (df['date'] == current_date) & 
            (df['source'] == source_name) &
            (df['metric_title'] == metric_title) &
            (df['category'] == category) &
            (df['sub_category'].fillna('') == sub_category)
        )
        
        if mask.any():
            # Update existing row
            row_idx = df[mask].index[0]
            df.at[row_idx, 'timestamp'] = current_timestamp
            df.at[row_idx, 'value'] = value
            logger.debug(f"Updated: {source_name}/{metric_title}/{category}/{sub_category} = {value}")
        else:
            # Create new row
            new_row = {
                'date': current_date,
                'timestamp': current_timestamp,
                'source': source_name,
                'metric_title': metric_title,
                'category': category,
                'sub_category': sub_category,
                'value': value
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            logger.debug(f"Added: {source_name}/{metric_title}/{category}/{sub_category} = {value}")
    
    logger.info(f"Processed {len(data)} metrics for {source_name} on {current_date}")
    return df


def process_worker_result_long(
    source_name: str,
    data: List[Dict[str, Any]],
    output_dir: str = None
) -> bool:
    """
    Process worker results in LONG format (Date/Source/Metric Title/Category/Value).
    
    Args:
        source_name: Worker identifier (e.g., 'smax')
        data: List of dicts with keys: metric_title, category, value
        output_dir: Output directory (defaults to script directory)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Load DataFrame
        df = load_or_create_csv(output_dir, use_long_format=True)
        
        # Track new metric titles for documentation
        existing_metrics = set()
        if not df.empty and 'metric_title' in df.columns:
            existing_metrics = set(df['metric_title'].dropna().unique())
        
        # Update with new data
        df = update_snapshot_long(df, source_name, data)
        
        # Save
        save_csv(df, output_dir)
        
        # Check for new metric titles and update data dictionary
        new_metrics = set(item.get('metric_title', '') for item in data) - existing_metrics
        if new_metrics:
            update_data_dictionary_long(new_metrics, source_name, output_dir)
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing worker result: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def update_data_dictionary_long(
    new_metrics: Set[str],
    source_name: str,
    output_dir: str = None
):
    """
    Update DATA_DICTIONARY.md with new metric titles (long format).
    
    Args:
        new_metrics: Set of new metric title names
        source_name: The source worker that introduced these metrics
        output_dir: Directory for the data dictionary file
    """
    if not new_metrics:
        return
    
    dict_path = get_output_path(DATA_DICTIONARY_FILENAME, output_dir)
    current_date = datetime.now().strftime('%Y-%m-%d')
    current_time = datetime.now().strftime('%H:%M:%S')
    
    # Check if file exists and read existing content
    if os.path.exists(dict_path):
        with open(dict_path, 'r', encoding='utf-8') as f:
            existing_content = f.read()
    else:
        # Create new file with header for long format
        existing_content = """# Data Dictionary
## KPI Snapshots Schema Documentation

This file is **automatically generated** by the Snapshot Scraper system.
New metrics are documented here as they are detected.

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
"""
    
    # Append new metric entries
    new_entries = []
    for metric in sorted(new_metrics):
        if metric:  # Skip empty strings
            description = f"Report from {source_name}. [Add description]"
            entry = f"| {metric} | {source_name} | {description} | {current_date} {current_time} |"
            new_entries.append(entry)
    
    if new_entries:
        with open(dict_path, 'w', encoding='utf-8') as f:
            f.write(existing_content)
            f.write('\n'.join(new_entries))
            f.write('\n')
        
        logger.info(f"Updated data dictionary with {len(new_entries)} new metric(s)")
        for entry in new_entries:
            logger.info(f"  New metric documented: {entry.split('|')[1].strip()}")


# ============================================================
# WIDE FORMAT FUNCTIONS (Legacy - one row per source with KPI columns)
# ============================================================



def update_snapshot(
    df: pd.DataFrame,
    source_name: str,
    data: Dict[str, Any],
    current_date: str = None
) -> pd.DataFrame:
    """
    Update or insert a snapshot row using the idempotent replacement logic.
    
    Logic:
    - Look for row matching [current_date] AND [source_name]
    - If found: Overwrite the existing values
    - If not found (new day/source): Append a new row
    
    Args:
        df: Existing DataFrame
        source_name: Identifier for the data source (e.g., 'smax')
        data: Dictionary of KPI values to store
        current_date: Date string (YYYY-MM-DD), defaults to today
        
    Returns:
        Updated DataFrame
    """
    if current_date is None:
        current_date = datetime.now().strftime('%Y-%m-%d')
    
    current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Add any new columns from data that don't exist yet
    for col in data.keys():
        if col not in df.columns:
            df[col] = None
    
    # Check if row exists for this date and source
    mask = (df['date'] == current_date) & (df['source_name'] == source_name)
    
    if mask.any():
        # Update existing row
        row_idx = df[mask].index[0]
        df.at[row_idx, 'timestamp'] = current_timestamp
        for key, value in data.items():
            df.at[row_idx, key] = value
        logger.info(f"Updated existing row for {source_name} on {current_date}")
    else:
        # Create new row
        new_row = {
            'date': current_date,
            'timestamp': current_timestamp,
            'source_name': source_name,
            **data
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        logger.info(f"Added new row for {source_name} on {current_date}")
    
    return df


def get_existing_columns(output_dir: str = None) -> Set[str]:
    """Get the set of columns currently in the CSV."""
    csv_path = get_output_path(CSV_FILENAME, output_dir)
    
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path, nrows=0)  # Just read headers
            return set(df.columns)
        except Exception:
            return set(CORE_COLUMNS)
    return set(CORE_COLUMNS)


def update_data_dictionary(
    new_columns: Set[str],
    source_name: str,
    output_dir: str = None
):
    """
    Update the DATA_DICTIONARY.md file with new columns.
    
    This implements the Auto-Doc Engine requirement:
    - Detects new columns
    - Appends entries with column name, source, and first detected timestamp
    
    Args:
        new_columns: Set of column names that are new
        source_name: The source worker that introduced these columns
        output_dir: Directory for the data dictionary file
    """
    if not new_columns:
        return
    
    dict_path = get_output_path(DATA_DICTIONARY_FILENAME, output_dir)
    current_date = datetime.now().strftime('%Y-%m-%d')
    current_time = datetime.now().strftime('%H:%M:%S')
    
    # Check if file exists and read existing content
    if os.path.exists(dict_path):
        with open(dict_path, 'r', encoding='utf-8') as f:
            existing_content = f.read()
    else:
        # Create new file with header
        existing_content = """# Data Dictionary
## KPI Snapshots Schema Documentation

This file is **automatically generated** by the Snapshot Scraper system.
New columns are documented here as they are detected.

---

| Column Name | Source | Description | First Detected |
| :--- | :--- | :--- | :--- |
| date | System | The date of the snapshot (YYYY-MM-DD) | System |
| timestamp | System | Last update timestamp for the row | System |
| source_name | System | Identifier of the data source/worker | System |
"""
    
    # Append new column entries
    new_entries = []
    for col in sorted(new_columns):
        if col not in CORE_COLUMNS:  # Don't re-document core columns
            description = f"KPI from {source_name} worker. [Add description]"
            entry = f"| {col} | {source_name} | {description} | {current_date} {current_time} |"
            new_entries.append(entry)
    
    if new_entries:
        with open(dict_path, 'w', encoding='utf-8') as f:
            f.write(existing_content)
            f.write('\n'.join(new_entries))
            f.write('\n')
        
        logger.info(f"Updated data dictionary with {len(new_entries)} new column(s)")
        for entry in new_entries:
            logger.info(f"  New column documented: {entry.split('|')[1].strip()}")


def process_worker_result(
    source_name: str,
    data: Dict[str, Any],
    output_dir: str = None
) -> bool:
    """
    Main entry point for processing a worker's scraped data.
    
    This function:
    1. Loads the existing CSV
    2. Checks for new columns (for documentation)
    3. Updates the snapshot using idempotent logic
    4. Saves the CSV
    5. Updates the data dictionary if needed
    
    Args:
        source_name: Worker identifier
        data: Dictionary of scraped KPI values
        output_dir: Output directory (defaults to script directory)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get existing columns before update
        existing_cols = get_existing_columns(output_dir)
        
        # Load DataFrame
        df = load_or_create_csv(output_dir)
        
        # Update with new data
        df = update_snapshot(df, source_name, data)
        
        # Save
        save_csv(df, output_dir)
        
        # Check for new columns and update data dictionary
        new_cols = set(data.keys()) - existing_cols
        if new_cols:
            update_data_dictionary(new_cols, source_name, output_dir)
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing worker result: {e}")
        return False


def get_latest_snapshot(source_name: str = None, output_dir: str = None) -> pd.DataFrame:
    """
    Get the latest snapshot(s) from the CSV.
    
    Args:
        source_name: Optional filter by source
        output_dir: Output directory
        
    Returns:
        DataFrame with latest row(s)
    """
    df = load_or_create_csv(output_dir)
    
    if df.empty:
        return df
    
    # Get today's date
    today = datetime.now().strftime('%Y-%m-%d')
    
    if source_name:
        mask = (df['date'] == today) & (df['source_name'] == source_name)
    else:
        mask = df['date'] == today
    
    return df[mask]


def cleanup_old_data(days_to_keep: int = 90, output_dir: str = None):
    """
    Remove data older than specified days.
    Useful for maintenance to prevent CSV from growing too large.
    
    Args:
        days_to_keep: Number of days of data to retain
        output_dir: Output directory
    """
    df = load_or_create_csv(output_dir)
    
    if df.empty:
        return
    
    cutoff_date = (datetime.now() - pd.Timedelta(days=days_to_keep)).strftime('%Y-%m-%d')
    df = df[df['date'] >= cutoff_date]
    
    save_csv(df, output_dir)
    logger.info(f"Cleaned up data older than {cutoff_date}")
