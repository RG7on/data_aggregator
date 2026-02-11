"""
Configuration Loader
====================
Single source of truth for all settings and credentials.
Reads from config/settings.json and config/credentials.json.
"""

import os
import json
import logging

logger = logging.getLogger('config')

# ── Path constants ────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR   = os.path.join(PROJECT_ROOT, 'config')
SETTINGS_PATH    = os.path.join(CONFIG_DIR, 'settings.json')
CREDENTIALS_PATH = os.path.join(CONFIG_DIR, 'credentials.json')

# ── Caches ────────────────────────────────────────────────────────────────
_settings_cache: dict = None
_credentials_cache: dict = None


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
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            logger.debug(f"Loaded config from {path}")
            return loaded
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e} — using defaults")
    else:
        logger.info(f"Config file not found: {path} — using defaults")
        # Write defaults so the user has a template
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(defaults, f, indent=2)
            logger.info(f"Created default config at {path}")
        except Exception:
            pass
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
                "timeout_nav_ms": 30000,
                "timeout_short_ms": 1500,
                "timeout_medium_ms": 2500,
                "timeout_long_ms": 8000
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
