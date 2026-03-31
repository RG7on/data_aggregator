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
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_timestamp TEXT    NOT NULL,           -- when the scrape ran
    data_datetime    TEXT    NOT NULL DEFAULT '', -- report DateTime: 'YYYY-MM-DD HH:MM:SS' (interval) or 'YYYY-MM-DD' (consolidated)
    source           TEXT    NOT NULL,
    report_name      TEXT    NOT NULL DEFAULT '', -- settings label of the report
    metric_title     TEXT    NOT NULL,
    category         TEXT    NOT NULL DEFAULT '', -- call type / group key
    sub_category     TEXT    NOT NULL DEFAULT '', -- additional grouping (SMAX only)
    value            TEXT    NOT NULL DEFAULT ''
);
"""

_CREATE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_kpi_dedup
    ON kpi_snapshots (data_datetime, source, report_name, metric_title, category, sub_category);
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
        conn.execute(_CREATE_SCRAPE_LOG)
        # Schema migrations for existing databases (safe to run repeatedly)
        # Detect old schema: if either data_date or interval columns exist,
        # drop and recreate the table (development data only — no production loss).
        cols = {row[1] for row in conn.execute("PRAGMA table_info(kpi_snapshots)").fetchall()}
        if 'data_date' in cols or 'interval' in cols or 'report_name' not in cols:
            conn.execute("DROP TABLE IF EXISTS kpi_snapshots")
            conn.execute(_CREATE_TABLE)
            conn.commit()
            logger.info("Schema migrated: rebuilt kpi_snapshots with current schema")
        # Rebuild dedup index
        conn.execute("DROP INDEX IF EXISTS idx_kpi_dedup")
        conn.execute(_CREATE_INDEX)
        conn.execute("DELETE FROM kpi_snapshots WHERE metric_title = 'Unknown Report'")
        conn.commit()
        logger.debug("Database initialized")
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════
#  WRITE  (upsert — insert or replace)
# ══════════════════════════════════════════════════════════════════════════

_UPSERT_SQL = """
INSERT INTO kpi_snapshots (scrape_timestamp, data_datetime, source, report_name, metric_title, category, sub_category, value)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (data_datetime, source, report_name, metric_title, category, sub_category)
DO UPDATE SET
    scrape_timestamp = excluded.scrape_timestamp,
    value            = excluded.value;
"""


def upsert_metrics(source_name: str, data: List[Dict[str, Any]],
                   current_date: str = None):
    """
    Insert or update a batch of metrics in one transaction.

    Each dict in *data* should have:
        metric_title, category (opt), sub_category (opt), interval (opt),
        data_date (opt — date the metrics are FOR), value
    """
    if not data:
        return

    if current_date is None:
        current_date = datetime.now().strftime('%Y-%m-%d')
    scraped_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    rows = []
    for item in data:
        # data_datetime: use the datetime embedded in the record (from the report's
        # DateTime column). Consolidated rows have no DateTime, fall back to today.
        data_datetime = item.get('data_datetime', '') or current_date
        rows.append((
            scraped_at,
            data_datetime,
            source_name,
            item.get('report_name', ''),
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
            "SELECT scrape_timestamp, data_datetime, source, report_name, metric_title, category, sub_category, value "
            "FROM kpi_snapshots ORDER BY data_datetime, source, report_name, metric_title, category",
            conn
        )
        return df
    finally:
        conn.close()


def query_by_date(start_date: str, end_date: str = None) -> pd.DataFrame:
    """Return rows within a date range (matches on the date portion of data_datetime)."""
    if end_date is None:
        end_date = start_date
    conn = _get_conn()
    try:
        df = pd.read_sql_query(
            "SELECT scrape_timestamp, data_datetime, source, report_name, metric_title, category, sub_category, value "
            "FROM kpi_snapshots WHERE substr(data_datetime, 1, 10) BETWEEN ? AND ? "
            "ORDER BY data_datetime, source, report_name, metric_title, category",
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
        cur = conn.execute("DELETE FROM kpi_snapshots WHERE substr(data_datetime, 1, 10) < ?", (cutoff,))
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
    Export a rolling window of the database to CSV (atomic write).

    The window size is controlled by ``csv_export_days`` in settings
    (default 30).  The full history stays in SQLite; the CSV only
    carries recent data so Power BI refreshes stay fast.

    Writes to:
      1. output/kpi_snapshots.csv  (always)
      2. shared_drive_path         (if configured in settings)
    """
    csv_days = get_global_settings().get('csv_export_days', 30)
    start = (datetime.now() - timedelta(days=csv_days)).strftime('%Y-%m-%d')
    end   = datetime.now().strftime('%Y-%m-%d')
    df = query_by_date(start, end)
    logger.info(f"CSV export window: {start} → {end} ({csv_days} days, {len(df)} rows)")

    # 1. Local CSV (atomic)
    if output_dir is None:
        output_dir = get_output_dir()
    local_csv = os.path.join(output_dir, CSV_FILENAME)
    _atomic_write_csv(df, local_csv)
    logger.info(f"Exported {len(df)} rows -> {local_csv}")

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
            logger.info(f"Exported {len(df)} rows -> {shared_drive_path} (shared drive)")
        except Exception as e:
            logger.error(f"Failed to write to shared drive: {e}")
            logger.error("Local CSV is still up-to-date - data is safe.")


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
        logger.warning(f"CSV columns {list(df.columns)} don't match expected schema - skipping migration")
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


def has_historical_data(source: str, label: str) -> bool:
    """
    Check if we already have a successful scrape logged for a historical report.

    Returns True when scrape_log contains a 'success' entry with row_count > 0
    for the given source + report_label.  This is the authoritative check:
    scrape_log.report_label always stores the config label string, which is
    consistent across runs — unlike kpi_snapshots.metric_title which stores the
    DOM page title and can differ from the config label.
    """
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT 1 FROM scrape_log "
            "WHERE source = ? AND report_label = ? AND status = 'success' AND row_count > 0 "
            "ORDER BY id DESC LIMIT 1",
            (source, label)
        )
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        conn.close()
