"""
Common Utilities for Modular Snapshot Scraper
==============================================
Handles CSV operations, snapshot logic, and automatic data dictionary generation.
"""

import os
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Set
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

# Core columns that are always present
CORE_COLUMNS = ['date', 'timestamp', 'source_name']


def get_output_path(filename: str, output_dir: str = None) -> str:
    """Get the full path for an output file."""
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    return os.path.join(output_dir, filename)


def load_or_create_csv(output_dir: str = None) -> pd.DataFrame:
    """
    Load existing CSV or create a new one with base columns.
    
    Returns:
        pandas DataFrame with at least the core columns
    """
    csv_path = get_output_path(CSV_FILENAME, output_dir)
    
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            logger.info(f"Loaded existing CSV with {len(df)} rows")
            return df
        except Exception as e:
            logger.error(f"Error loading CSV: {e}")
            # Return empty dataframe if load fails
            return pd.DataFrame(columns=CORE_COLUMNS)
    else:
        logger.info("Creating new CSV file")
        return pd.DataFrame(columns=CORE_COLUMNS)


def save_csv(df: pd.DataFrame, output_dir: str = None):
    """Save DataFrame to CSV file."""
    csv_path = get_output_path(CSV_FILENAME, output_dir)
    df.to_csv(csv_path, index=False)
    logger.info(f"Saved CSV to {csv_path}")


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
