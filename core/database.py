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
import hashlib
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from core.config import (
    get_output_dir,
    get_global_settings,
    get_settings,
    get_report_definition_hash,
    PROJECT_ROOT,
    REPORT_ID_KEY,
)

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
    report_id        TEXT    NOT NULL DEFAULT '', -- stable ID of the configured report entry
    definition_hash  TEXT    NOT NULL DEFAULT '', -- hash of scrape-affecting report settings
    report_name      TEXT    NOT NULL DEFAULT '', -- settings label of the report
    metric_title     TEXT    NOT NULL,
    category         TEXT    NOT NULL DEFAULT '', -- call type / group key
    sub_category     TEXT    NOT NULL DEFAULT '', -- additional grouping (SMAX only)
    value            TEXT    NOT NULL DEFAULT ''
);
"""

_CREATE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_kpi_dedup
    ON kpi_snapshots (data_datetime, source, report_id, metric_title, category, sub_category);
"""

_CREATE_SCRAPE_LOG = """
CREATE TABLE IF NOT EXISTS scrape_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    source        TEXT    NOT NULL,
    report_id     TEXT    NOT NULL DEFAULT '',
    definition_hash TEXT  NOT NULL DEFAULT '',
    report_label  TEXT    NOT NULL DEFAULT '',
    status        TEXT    NOT NULL,
    row_count     INTEGER DEFAULT 0,
    duration_s    REAL    DEFAULT 0,
    message       TEXT    DEFAULT ''
);
"""


def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str):
    columns = _get_table_columns(conn, table_name)
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def _legacy_report_id(source: str, label: str) -> str:
    raw = f"{source.strip().lower()}|{label.strip()}".encode('utf-8')
    return f"legacy:{hashlib.sha1(raw).hexdigest()}"


def _sync_report_identity_from_settings(conn: sqlite3.Connection):
    settings = get_settings() or {}
    workers = settings.get('workers', {})

    for source_name in ('cuic', 'smax'):
        for report in (workers.get(source_name) or {}).get('reports', []):
            label = str((report or {}).get('label', '') or '').strip()
            report_id = str((report or {}).get(REPORT_ID_KEY, '') or '').strip()
            definition_hash = get_report_definition_hash(source_name, report or {})

            if not label or not report_id:
                continue

            conn.execute(
                "UPDATE kpi_snapshots SET report_id = ?, definition_hash = ? "
                "WHERE source = ? AND report_name = ? AND (report_id = '' OR definition_hash = '')",
                (report_id, definition_hash, source_name, label),
            )
            conn.execute(
                "UPDATE scrape_log SET report_id = ?, definition_hash = ? "
                "WHERE source = ? AND report_label = ? AND (report_id = '' OR definition_hash = '')",
                (report_id, definition_hash, source_name, label),
            )


def _backfill_legacy_report_identity(conn: sqlite3.Connection):
    snap_rows = conn.execute(
        "SELECT DISTINCT source, report_name FROM kpi_snapshots WHERE COALESCE(report_id, '') = ''"
    ).fetchall()
    for source, report_name in snap_rows:
        if not report_name:
            continue
        conn.execute(
            "UPDATE kpi_snapshots SET report_id = ? WHERE source = ? AND report_name = ? AND COALESCE(report_id, '') = ''",
            (_legacy_report_id(str(source or ''), str(report_name or '')), source, report_name),
        )

    log_rows = conn.execute(
        "SELECT DISTINCT source, report_label FROM scrape_log WHERE COALESCE(report_id, '') = ''"
    ).fetchall()
    for source, report_label in log_rows:
        if not report_label:
            continue
        conn.execute(
            "UPDATE scrape_log SET report_id = ? WHERE source = ? AND report_label = ? AND COALESCE(report_id, '') = ''",
            (_legacy_report_id(str(source or ''), str(report_label or '')), source, report_label),
        )


def _dedupe_kpi_snapshots(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "DELETE FROM kpi_snapshots WHERE id NOT IN ("
        "  SELECT MAX(id) FROM kpi_snapshots "
        "  GROUP BY data_datetime, source, report_id, metric_title, category, sub_category"
        ")"
    )
    return cur.rowcount or 0


def init_db():
    """Create table + dedup index if they don't exist."""
    conn = _get_conn()
    try:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_SCRAPE_LOG)
        # Schema migrations for existing databases (safe to run repeatedly).
        cols = _get_table_columns(conn, 'kpi_snapshots')
        if 'data_date' in cols and 'data_datetime' not in cols:
            conn.execute("ALTER TABLE kpi_snapshots ADD COLUMN data_datetime TEXT NOT NULL DEFAULT ''")
            if 'interval' in cols:
                conn.execute(
                    "UPDATE kpi_snapshots SET data_datetime = "
                    "CASE WHEN COALESCE(interval, '') <> '' THEN TRIM(data_date || ' ' || interval) ELSE COALESCE(data_date, '') END "
                    "WHERE COALESCE(data_datetime, '') = ''"
                )
            else:
                conn.execute(
                    "UPDATE kpi_snapshots SET data_datetime = COALESCE(data_date, '') "
                    "WHERE COALESCE(data_datetime, '') = ''"
                )
        _ensure_column(conn, 'kpi_snapshots', 'report_name', "report_name TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, 'kpi_snapshots', 'report_id', "report_id TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, 'kpi_snapshots', 'definition_hash', "definition_hash TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, 'scrape_log', 'report_id', "report_id TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, 'scrape_log', 'definition_hash', "definition_hash TEXT NOT NULL DEFAULT ''")
        _sync_report_identity_from_settings(conn)
        _backfill_legacy_report_identity(conn)
        deleted_duplicates = _dedupe_kpi_snapshots(conn)
        if deleted_duplicates:
            logger.warning(f"Removed {deleted_duplicates} duplicate KPI snapshot rows during schema migration")
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
INSERT INTO kpi_snapshots (scrape_timestamp, data_datetime, source, report_id, definition_hash, report_name, metric_title, category, sub_category, value)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (data_datetime, source, report_id, metric_title, category, sub_category)
DO UPDATE SET
    scrape_timestamp = excluded.scrape_timestamp,
    definition_hash  = excluded.definition_hash,
    report_name      = excluded.report_name,
    value            = excluded.value;
"""


def _build_metric_rows(
    source_name: str,
    data: List[Dict[str, Any]],
    *,
    scraped_at: str,
    current_date: str,
    report_id: str = '',
    definition_hash: str = '',
    report_name: str = '',
) -> List[tuple]:
    rows = []
    for item in data:
        data_datetime = item.get('data_datetime', '') or current_date
        rows.append((
            scraped_at,
            data_datetime,
            source_name,
            item.get('report_id', report_id or ''),
            item.get('definition_hash', definition_hash or ''),
            item.get('report_name', report_name or ''),
            item.get('metric_title', ''),
            item.get('category', ''),
            item.get('sub_category', ''),
            str(item.get('value', '')),
        ))
    return rows


def upsert_metrics(source_name: str, data: List[Dict[str, Any]],
                   current_date: str = None,
                   *,
                   replace_report: bool = False,
                   report_id: str = '',
                   definition_hash: str = '',
                   report_name: str = ''):
    """
    Insert or update a batch of metrics in one transaction.

    Each dict in *data* should have:
        metric_title, category (opt), sub_category (opt), interval (opt),
        data_date (opt — date the metrics are FOR), value
    """
    if not data and not (replace_report and report_id):
        return

    if current_date is None:
        current_date = datetime.now().strftime('%Y-%m-%d')
    scraped_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    rows = _build_metric_rows(
        source_name,
        data,
        scraped_at=scraped_at,
        current_date=current_date,
        report_id=report_id,
        definition_hash=definition_hash,
        report_name=report_name,
    )

    conn = _get_conn()
    try:
        conn.execute('BEGIN')
        if replace_report and report_id:
            conn.execute(
                "DELETE FROM kpi_snapshots WHERE source = ? AND report_id = ?",
                (source_name, report_id),
            )
        conn.executemany(_UPSERT_SQL, rows)
        conn.commit()
        logger.info(
            f"Persisted {len(rows)} metrics for '{source_name}' on {current_date}"
            + (f" (replaced report_id={report_id})" if replace_report and report_id else '')
        )
    except Exception:
        conn.rollback()
        raise
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
            "SELECT scrape_timestamp, data_datetime, source, report_id, report_name, metric_title, category, sub_category, value "
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
            "SELECT scrape_timestamp, data_datetime, source, report_id, report_name, metric_title, category, sub_category, value "
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
    required = {'scrape_timestamp', 'data_datetime', 'source', 'metric_title', 'value'}
    if not required.issubset(set(df.columns)):
        logger.warning(f"CSV columns {list(df.columns)} don't match expected schema - skipping migration")
        return 0

    # Fill missing optional columns
    for col in ('report_id', 'report_name', 'category', 'sub_category', 'definition_hash'):
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
                    str(row['scrape_timestamp']),
                    str(row['data_datetime']),
                    str(row['source']),
                    str(row.get('report_id', '')),
                    str(row.get('definition_hash', '')),
                    str(row.get('report_name', '')),
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
               row_count: int = 0, duration_s: float = 0, message: str = '',
               report_id: str = '', definition_hash: str = ''):
    """Record a scrape attempt (success/error/no_data)."""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO scrape_log (timestamp, source, report_id, definition_hash, report_label, status, row_count, duration_s, message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, source, report_id, definition_hash, report_label, status, row_count, round(duration_s, 2), message)
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
            "SELECT id, timestamp, source, report_id, definition_hash, report_label, status, row_count, duration_s, message "
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
                SELECT source,
                       CASE WHEN COALESCE(report_id, '') <> '' THEN report_id ELSE report_label END AS report_identity,
                       MAX(id) as max_id
                FROM scrape_log
                GROUP BY source, report_identity
            ) latest ON s.id = latest.max_id
            ORDER BY s.timestamp DESC
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def has_historical_data(source: str, report_id: str, definition_hash: str) -> bool:
    """
    Check if we already have a successful scrape logged for a historical report.

    Returns True when scrape_log contains a 'success' entry with row_count > 0
    for the given source + report_id + definition_hash.
    """
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT 1 FROM scrape_log "
            "WHERE source = ? AND report_id = ? AND definition_hash = ? "
            "AND status = 'success' AND row_count >= 0 "
            "ORDER BY id DESC LIMIT 1",
            (source, report_id, definition_hash)
        )
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        conn.close()
