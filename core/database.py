"""
Database Layer (SQLite)
=======================
Local source-of-truth for all scraped KPI data.

Architecture:
  1. Workers write → SQLite (fast, atomic, corruption-proof)
  2. After every run → export CSV to output/ (and optionally shared drive)
  3. Power BI reads the CSV — never touches the database

The CSV is a *projection* of the database, not the other way around.
"""

import os
import sqlite3
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from core.config import get_output_dir, get_global_settings, PROJECT_ROOT

logger = logging.getLogger('database')

# ── Paths ─────────────────────────────────────────────────────────────────
DB_FILENAME = "kpi_data.db"
CSV_FILENAME = "kpi_snapshots.csv"


def _db_path() -> str:
    """Database lives in output/ alongside the CSV."""
    return os.path.join(get_output_dir(), DB_FILENAME)


def _get_conn() -> sqlite3.Connection:
    """Open a connection with WAL mode for safe concurrent reads."""
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")      # safe for readers
    conn.execute("PRAGMA synchronous=NORMAL")     # good perf, still safe
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ══════════════════════════════════════════════════════════════════════════
#  SCHEMA
# ══════════════════════════════════════════════════════════════════════════

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS kpi_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT    NOT NULL,
    timestamp     TEXT    NOT NULL,
    source        TEXT    NOT NULL,
    metric_title  TEXT    NOT NULL,
    category      TEXT    NOT NULL DEFAULT '',
    sub_category  TEXT    NOT NULL DEFAULT '',
    value         TEXT    NOT NULL DEFAULT ''
);
"""

_CREATE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_kpi_dedup
    ON kpi_snapshots (date, source, metric_title, category, sub_category);
"""

_CREATE_SCRAPE_LOG = """
CREATE TABLE IF NOT EXISTS scrape_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    source        TEXT    NOT NULL,
    report_label  TEXT    NOT NULL DEFAULT '',
    status        TEXT    NOT NULL,
    row_count     INTEGER DEFAULT 0,
    duration_s    REAL    DEFAULT 0,
    message       TEXT    DEFAULT ''
);
"""


def init_db():
    """Create table + dedup index if they don't exist."""
    conn = _get_conn()
    try:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_INDEX)
        conn.execute(_CREATE_SCRAPE_LOG)
        conn.commit()
        logger.debug("Database initialized")
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════
#  WRITE  (upsert — insert or replace)
# ══════════════════════════════════════════════════════════════════════════

_UPSERT_SQL = """
INSERT INTO kpi_snapshots (date, timestamp, source, metric_title, category, sub_category, value)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (date, source, metric_title, category, sub_category)
DO UPDATE SET
    timestamp = excluded.timestamp,
    value     = excluded.value;
"""


def upsert_metrics(source_name: str, data: List[Dict[str, Any]],
                   current_date: str = None):
    """
    Insert or update a batch of metrics in one transaction.

    Each dict in *data* should have:
        metric_title, category (opt), sub_category (opt), value
    """
    if not data:
        return

    if current_date is None:
        current_date = datetime.now().strftime('%Y-%m-%d')
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    rows = []
    for item in data:
        rows.append((
            current_date,
            ts,
            source_name,
            item.get('metric_title', ''),
            item.get('category', ''),
            item.get('sub_category', ''),
            str(item.get('value', '')),
        ))

    conn = _get_conn()
    try:
        conn.executemany(_UPSERT_SQL, rows)
        conn.commit()
        logger.info(f"Upserted {len(rows)} metrics for '{source_name}' on {current_date}")
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════
#  READ
# ══════════════════════════════════════════════════════════════════════════

def query_all() -> pd.DataFrame:
    """Return the entire table as a DataFrame (for CSV export)."""
    conn = _get_conn()
    try:
        df = pd.read_sql_query(
            "SELECT date, timestamp, source, metric_title, category, sub_category, value "
            "FROM kpi_snapshots ORDER BY date, source, metric_title",
            conn
        )
        return df
    finally:
        conn.close()


def query_by_date(start_date: str, end_date: str = None) -> pd.DataFrame:
    """Return rows within a date range."""
    if end_date is None:
        end_date = start_date
    conn = _get_conn()
    try:
        df = pd.read_sql_query(
            "SELECT date, timestamp, source, metric_title, category, sub_category, value "
            "FROM kpi_snapshots WHERE date BETWEEN ? AND ? "
            "ORDER BY date, source, metric_title",
            conn, params=(start_date, end_date)
        )
        return df
    finally:
        conn.close()


def row_count() -> int:
    """Quick row count without loading data."""
    conn = _get_conn()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM kpi_snapshots")
        return cur.fetchone()[0]
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════
#  MAINTENANCE
# ══════════════════════════════════════════════════════════════════════════

def cleanup_old_data(days_to_keep: int = None):
    """Delete rows older than *days_to_keep* (from settings if not given)."""
    if days_to_keep is None:
        days_to_keep = get_global_settings().get('data_retention_days', 90)

    cutoff = (datetime.now() - timedelta(days=days_to_keep)).strftime('%Y-%m-%d')
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM kpi_snapshots WHERE date < ?", (cutoff,))
        deleted = cur.rowcount
        conn.commit()
        if deleted:
            conn.execute("VACUUM")  # reclaim space
            logger.info(f"Retention cleanup: deleted {deleted} rows older than {cutoff}")
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════
#  CSV EXPORT  (the "projection" that Power BI reads)
# ══════════════════════════════════════════════════════════════════════════

def export_csv(output_dir: str = None, shared_drive_path: str = None):
    """
    Export the full database to CSV (atomic write).

    Writes to:
      1. output/kpi_snapshots.csv  (always)
      2. shared_drive_path         (if configured in settings)
    """
    df = query_all()

    # 1. Local CSV (atomic)
    if output_dir is None:
        output_dir = get_output_dir()
    local_csv = os.path.join(output_dir, CSV_FILENAME)
    _atomic_write_csv(df, local_csv)
    logger.info(f"Exported {len(df)} rows → {local_csv}")

    # 2. Shared drive CSV (if configured)
    if shared_drive_path is None:
        shared_drive_path = get_global_settings().get('shared_drive_csv', '')

    if shared_drive_path:
        try:
            # Ensure parent dir exists (shared drive may have subfolders)
            parent = os.path.dirname(shared_drive_path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            _atomic_write_csv(df, shared_drive_path)
            logger.info(f"Exported {len(df)} rows → {shared_drive_path} (shared drive)")
        except Exception as e:
            logger.error(f"Failed to write to shared drive: {e}")
            logger.error("Local CSV is still up-to-date — data is safe.")


def _atomic_write_csv(df: pd.DataFrame, path: str):
    """Write to .tmp then rename — readers never see a half-written file."""
    tmp = path + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


# ══════════════════════════════════════════════════════════════════════════
#  MIGRATION — one-time import of existing CSV into SQLite
# ══════════════════════════════════════════════════════════════════════════

def migrate_csv_to_db(csv_path: str = None):
    """
    Import an existing kpi_snapshots.csv into the database.
    Skips rows that already exist (dedup via UNIQUE index).
    Safe to run multiple times.
    """
    if csv_path is None:
        csv_path = os.path.join(get_output_dir(), CSV_FILENAME)

    if not os.path.exists(csv_path):
        logger.info("No existing CSV to migrate")
        return 0

    df = pd.read_csv(csv_path)
    if df.empty:
        return 0

    # Ensure expected columns
    required = {'date', 'timestamp', 'source', 'metric_title', 'value'}
    if not required.issubset(set(df.columns)):
        logger.warning(f"CSV columns {list(df.columns)} don't match expected schema — skipping migration")
        return 0

    # Fill missing optional columns
    for col in ('category', 'sub_category'):
        if col not in df.columns:
            df[col] = ''
    df = df.fillna('')

    init_db()
    conn = _get_conn()
    imported = 0
    try:
        for _, row in df.iterrows():
            try:
                conn.execute(_UPSERT_SQL, (
                    str(row['date']),
                    str(row['timestamp']),
                    str(row['source']),
                    str(row['metric_title']),
                    str(row.get('category', '')),
                    str(row.get('sub_category', '')),
                    str(row.get('value', '')),
                ))
                imported += 1
            except Exception:
                pass  # skip bad rows silently
        conn.commit()
        logger.info(f"Migrated {imported} rows from CSV into SQLite")
    finally:
        conn.close()

    return imported


# ══════════════════════════════════════════════════════════════════════════
#  SCRAPE LOG — per-report scrape tracking for the control panel
# ══════════════════════════════════════════════════════════════════════════

def log_scrape(source: str, report_label: str, status: str,
               row_count: int = 0, duration_s: float = 0, message: str = ''):
    """Record a scrape attempt (success/error/no_data)."""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO scrape_log (timestamp, source, report_label, status, row_count, duration_s, message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, source, report_label, status, row_count, round(duration_s, 2), message)
        )
        conn.commit()
    except Exception as e:
        logger.debug(f"Failed to log scrape: {e}")
    finally:
        conn.close()


def get_scrape_log(limit: int = 100) -> List[Dict[str, Any]]:
    """Return recent scrape log entries (newest first)."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT id, timestamp, source, report_label, status, row_count, duration_s, message "
            "FROM scrape_log ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def get_latest_scrape_status() -> List[Dict[str, Any]]:
    """Get the most recent scrape result for each source + report_label."""
    conn = _get_conn()
    try:
        cur = conn.execute("""
            SELECT s.* FROM scrape_log s
            INNER JOIN (
                SELECT source, report_label, MAX(id) as max_id
                FROM scrape_log GROUP BY source, report_label
            ) latest ON s.id = latest.max_id
            ORDER BY s.timestamp DESC
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def has_historical_data(source: str, metric_title: str) -> bool:
    """
    Check if we already have successfully-scraped data for a historical report.

    Returns True if there is at least one row in kpi_snapshots for the given
    source + metric_title AND the last scrape_log entry for it was a success.
    This lets the worker skip re-scraping reports whose data never changes.
    """
    conn = _get_conn()
    try:
        # Check 1: do we have actual data rows?
        cur = conn.execute(
            "SELECT COUNT(*) FROM kpi_snapshots WHERE source = ? AND metric_title = ?",
            (source, metric_title)
        )
        data_count = cur.fetchone()[0]
        if data_count == 0:
            return False

        # Check 2: was the last scrape successful?
        cur = conn.execute(
            "SELECT status FROM scrape_log "
            "WHERE source = ? AND report_label = ? "
            "ORDER BY id DESC LIMIT 1",
            (source, metric_title)
        )
        row = cur.fetchone()
        if row and row[0] == 'success':
            return True

        return False
    except Exception:
        return False
    finally:
        conn.close()

    return imported
