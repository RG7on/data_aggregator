"""
Configuration Loader
====================
Single source of truth for all settings and credentials.
Reads from config/settings.json and config/credentials.json.
"""

import os
import json
import logging
import hashlib
from copy import deepcopy
from typing import Any, Dict, Tuple
from uuid import uuid4

logger = logging.getLogger('config')

# ── Path constants ────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR   = os.path.join(PROJECT_ROOT, 'config')
SETTINGS_PATH    = os.path.join(CONFIG_DIR, 'settings.json')
CREDENTIALS_PATH = os.path.join(CONFIG_DIR, 'credentials.json')

# ── Caches ────────────────────────────────────────────────────────────────
_settings_cache: dict = None
_credentials_cache: dict = None

REPORT_ID_KEY = 'report_id'


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _new_report_id() -> str:
    return uuid4().hex


def _normalize_cuic_path(value: str) -> str:
    return str(value or '').replace('\\', '/').strip().strip('/')


def normalize_report_config(worker_name: str, report: dict) -> Tuple[dict, bool]:
    """Return a normalized report config and whether it changed."""
    normalized = dict(report or {})
    changed = False

    report_id = str(normalized.get(REPORT_ID_KEY, '') or '').strip()
    if not report_id:
        normalized[REPORT_ID_KEY] = _new_report_id()
        changed = True

    if worker_name == 'cuic':
        folder = _normalize_cuic_path(normalized.get('folder', ''))
        name = str(normalized.get('name', '') or '').strip().strip('/')
        if normalized.get('folder', '') != folder:
            normalized['folder'] = folder
            changed = True
        if normalized.get('name', '') != name:
            normalized['name'] = name
            changed = True
    elif worker_name == 'smax':
        url = str(normalized.get('url', '') or '').strip()
        if normalized.get('url', '') != url:
            normalized['url'] = url
            changed = True

    return normalized, changed


def normalize_settings(settings: dict) -> Tuple[dict, bool]:
    """Ensure settings include stable report IDs and normalized report fields."""
    normalized = deepcopy(settings or {})
    changed = False

    workers = normalized.setdefault('workers', {})
    if not isinstance(workers, dict):
        normalized['workers'] = {}
        workers = normalized['workers']
        changed = True

    for worker_name in ('cuic', 'smax'):
        worker_cfg = workers.setdefault(worker_name, {})
        if not isinstance(worker_cfg, dict):
            workers[worker_name] = {}
            worker_cfg = workers[worker_name]
            changed = True

        reports = worker_cfg.get('reports', [])
        if not isinstance(reports, list):
            worker_cfg['reports'] = []
            reports = worker_cfg['reports']
            changed = True

        normalized_reports = []
        for report in reports:
            if not isinstance(report, dict):
                changed = True
                continue
            normalized_report, report_changed = normalize_report_config(worker_name, report)
            normalized_reports.append(normalized_report)
            changed = changed or report_changed or normalized_report != report

        if normalized_reports != reports:
            worker_cfg['reports'] = normalized_reports
            changed = True

    return normalized, changed


def get_report_definition_hash(worker_name: str, report: Dict[str, Any]) -> str:
    """Hash only the fields that change the dataset produced by a report entry."""
    report = report or {}

    if worker_name == 'cuic':
        payload = {
            'folder': _normalize_cuic_path(report.get('folder', '')),
            'name': str(report.get('name', '') or '').strip().strip('/'),
            'filters': report.get('filters') or {},
            'row_mode': report.get('row_mode', 'consolidated_only'),
            'columns': report.get('columns'),
        }
    elif worker_name == 'smax':
        payload = {
            'url': str(report.get('url', '') or '').strip(),
        }
    else:
        payload = deepcopy(report)
        payload.pop('label', None)
        payload.pop('enabled', None)
        payload.pop(REPORT_ID_KEY, None)

    return hashlib.sha256(_stable_json(payload).encode('utf-8')).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════

def get_settings() -> dict:
    """Return the full settings dict (cached after first load)."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = _load_json(SETTINGS_PATH, _default_settings())
    return _settings_cache


def get_credentials() -> dict:
    """Return the full credentials dict (cached after first load)."""
    global _credentials_cache
    if _credentials_cache is None:
        _credentials_cache = _load_json(CREDENTIALS_PATH, _default_credentials())
    return _credentials_cache


def get_global_settings() -> dict:
    """Shortcut: return just the 'global' section of settings."""
    return get_settings().get('global', {})


def get_worker_settings(worker_name: str) -> dict:
    """Return the settings block for a specific worker."""
    return get_settings().get('workers', {}).get(worker_name, {})


def get_worker_credentials(worker_name: str) -> dict:
    """Return username/password for a specific worker."""
    return get_credentials().get(worker_name, {})


def reload():
    """Force re-read from disk (useful after the UI saves new settings)."""
    global _settings_cache, _credentials_cache
    _settings_cache = None
    _credentials_cache = None


# ── Path helpers (resolve relative dirs against PROJECT_ROOT) ─────────────

def get_output_dir() -> str:
    rel = get_global_settings().get('output_dir', 'output')
    path = os.path.join(PROJECT_ROOT, rel)
    os.makedirs(path, exist_ok=True)
    return path


def get_log_dir() -> str:
    rel = get_global_settings().get('log_dir', 'logs')
    path = os.path.join(PROJECT_ROOT, rel)
    os.makedirs(path, exist_ok=True)
    return path


def get_docs_dir() -> str:
    path = os.path.join(PROJECT_ROOT, 'docs')
    os.makedirs(path, exist_ok=True)
    return path


# ══════════════════════════════════════════════════════════════════════════
#  INTERNAL
# ══════════════════════════════════════════════════════════════════════════

def _load_json(path: str, defaults: dict) -> dict:
    changed = False
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if path == SETTINGS_PATH:
                loaded, changed = normalize_settings(loaded)
                if changed:
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(loaded, f, indent=2)
            logger.debug(f"Loaded config from {path}")
            return loaded
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e} - using defaults")
    else:
        logger.info(f"Config file not found: {path} - using defaults")
        # Write defaults so the user has a template
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            to_write = defaults
            if path == SETTINGS_PATH:
                to_write, _ = normalize_settings(defaults)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(to_write, f, indent=2)
            logger.info(f"Created default config at {path}")
        except Exception:
            pass
    if path == SETTINGS_PATH:
        defaults, _ = normalize_settings(defaults)
    return defaults


def _default_settings() -> dict:
    return {
        "global": {
            "headless": True,
            "use_system_chrome": True,
            "screenshot_steps": False,
            "screenshot_errors": True,
            "log_level": "INFO",
            "output_dir": "output",
            "log_dir": "logs",
            "data_retention_days": 90,
            "shared_drive_csv": ""
        },
        "workers": {
            "cuic": {
                "enabled": True,
                "url": "https://148.151.32.77:8444/cuicui/Main.jsp",
                "reports": [
                    {
                        "label": "call_type_hist",
                        "folder": "Test",
                        "name": "Z Call Type Historical All Fields",
                        "enabled": True,
                        "filters": {}
                    },
                    {
                        "label": "agent_hist",
                        "folder": "Stock/CCE/CCE_AF_Historical",
                        "name": "Agent Historical All Fields",
                        "enabled": True,
                        "filters": {}
                    }
                ],
                "use_system_chrome": False,
                "timeout_nav_ms": 60000,
                "timeout_short_ms": 2000,
                "timeout_medium_ms": 5000,
                "timeout_long_ms": 15000
            },
            "smax": {
                "enabled": True,
                "base_url": "https://smax.corp.pdo.om",
                "report_urls": [],
                "page_load_timeout_ms": 120000,
                "element_wait_timeout_ms": 30000,
                "tab_stagger_delay_ms": 2000,
                "max_retries": 2
            }
        }
    }


def _default_credentials() -> dict:
    return {
        "cuic": {"username": "", "password": ""},
        "smax": {"username": "", "password": ""}
    }
