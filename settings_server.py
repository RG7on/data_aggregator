"""
Settings Server
================
Lightweight HTTP server for the Data Aggregator control panel.

Serves the settings UI and provides API endpoints for:
  - GET/POST  /api/settings     → read/write settings.json
  - GET/POST  /api/credentials  → read/write credentials.json
  - GET       /api/scrape-log   → recent scrape history from SQLite

Usage:  python settings_server.py          (opens browser automatically)
        python settings_server.py --port 9090
"""

import os
import sys
import json
import webbrowser
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from core.config import SETTINGS_PATH, CREDENTIALS_PATH
from core.database import init_db, get_scrape_log, get_latest_scrape_status
from core.agent_insights import (
    build_agent_insights,
    build_health_summary,
    build_report_insight,
    parse_agent_query_params,
)

PORT = 8580
UI_FILE = os.path.join(PROJECT_ROOT, 'ui', 'index.html')
UI_DIR  = os.path.join(PROJECT_ROOT, 'ui')

MIME_TYPES = {
    '.html': 'text/html',
    '.css':  'text/css',
    '.js':   'application/javascript',
    '.json': 'application/json',
    '.png':  'image/png',
    '.svg':  'image/svg+xml',
    '.ico':  'image/x-icon',
}

# Track running discovery tasks
_discovery_lock = threading.Lock()
_discovery_running = False

# Track running scrape tasks
_scrape_lock = threading.Lock()
_scrape_running = False
_scrape_thread = None


def _normalize_cuic_report_config(report_config):
    folder = str(report_config.get('folder', '') or '').replace('\\', '/').strip().strip('/')
    name = str(report_config.get('name', '') or '').strip().strip('/')
    raw_path = str(report_config.get('path', '') or '').replace('\\', '/').strip().strip('/')

    if raw_path and (not folder or not name):
        parts = [part.strip() for part in raw_path.split('/') if part.strip()]
        if len(parts) >= 2:
            folder = '/'.join(parts[:-1])
            name = parts[-1]

    return {
        'folder': folder,
        'name': name,
        'path': f"{folder}/{name}" if folder and name else name,
    }


def _validate_cuic_report_config(report_config):
    normalized = _normalize_cuic_report_config(report_config)
    if not normalized['name']:
        raise ValueError('Missing report name. Enter the full CUIC report path before validation.')
    if not normalized['folder']:
        raise ValueError('Invalid report path. Use the full CUIC report path, for example Folder/Report Name.')
    return normalized


def _validate_web_url(value, *, field_name):
    parsed = urlparse(str(value or '').strip())
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError(f'Invalid {field_name}. Enter a full http(s) URL.')
    return parsed.geturl()


class SettingsHandler(BaseHTTPRequestHandler):
    """Handle API requests and serve the control panel HTML."""

    def do_GET(self):
        path = urlparse(self.path).path

        if path in ('/', '/index.html'):
            self._serve_file(UI_FILE, 'text/html')
        elif path == '/api/settings':
            self._serve_json_file(SETTINGS_PATH)
        elif path == '/api/credentials':
            self._serve_json_file(CREDENTIALS_PATH)
        elif path == '/api/scrape-log':
            self._serve_scrape_log()
        elif path == '/api/scrape-status':
            self._serve_scrape_status()
        elif path == '/api/scrape-running':
            with _scrape_lock:
                self._send_json({'running': _scrape_running})
        elif path == '/api/agent/insights':
            self._serve_agent_insights()
        elif path == '/api/agent/health-summary':
            self._serve_agent_health_summary()
        elif path.startswith('/api/agent/report/'):
            self._serve_agent_report(path)
        elif path.startswith('/css/') or path.startswith('/js/'):
            # Serve static assets from ui/ directory
            # Security: reject path traversal attempts
            if '..' in path:
                self.send_error(400, 'Bad request')
                return
            file_path = os.path.join(UI_DIR, path.lstrip('/'))
            ext = os.path.splitext(file_path)[1].lower()
            mime = MIME_TYPES.get(ext, 'application/octet-stream')
            self._serve_file(file_path, mime)
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/api/settings':
            self._save_json_file(SETTINGS_PATH)
            # Invalidate cached config so workers pick up the new settings
            try:
                from core.config import reload as config_reload
                config_reload()
            except Exception:
                pass
        elif path == '/api/credentials':
            self._save_json_file(CREDENTIALS_PATH)
            try:
                from core.config import reload as config_reload
                config_reload()
            except Exception:
                pass
        elif path == '/api/discover-filters':
            self._discover_filters()
        elif path == '/api/discover-smax-properties':
            self._discover_smax_properties()
        elif path == '/api/run-scrape':
            self._run_scrape()
        elif path == '/api/clear-data':
            self._clear_data()
        else:
            self.send_error(404)

    # ── Filter wizard discovery ───────────────────────────────────────────

    def _discover_filters(self):
        """Launch a browser to read wizard fields for a given report config."""
        global _discovery_running
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            report_config = _validate_cuic_report_config(json.loads(body))

            with _discovery_lock:
                if _discovery_running:
                    self._send_json({'error': 'A discovery is already running. Please wait.'}, status=409)
                    return
                _discovery_running = True

            # Run discovery in the current thread (request blocks until done)
            try:
                from workers.cuic import Worker as CuicWorker
                result = CuicWorker.discover_wizard(report_config)
                self._send_json(result)
            finally:
                with _discovery_lock:
                    _discovery_running = False

        except json.JSONDecodeError as e:
            self._send_json({'error': f'Invalid JSON: {e}'}, status=400)
        except ValueError as e:
            self._send_json({'error': str(e)}, status=400)
        except Exception as e:
            with _discovery_lock:
                _discovery_running = False
            self._send_json({'error': str(e)}, status=500)

    # ── SMAX Report Properties discovery ──────────────────────────────────

    def _discover_smax_properties(self):
        """Launch a browser to read Report Properties from an SMAX report."""
        global _discovery_running
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            report_config = json.loads(body)
            report_config['url'] = _validate_web_url(report_config.get('url', ''), field_name='report URL')

            with _discovery_lock:
                if _discovery_running:
                    self._send_json({'error': 'A discovery is already running. Please wait.'}, status=409)
                    return
                _discovery_running = True

            try:
                from workers.smax_worker import Worker as SmaxWorker
                result = SmaxWorker.discover_properties(report_config)
                self._send_json(result)
            finally:
                with _discovery_lock:
                    _discovery_running = False

        except json.JSONDecodeError as e:
            self._send_json({'error': f'Invalid JSON: {e}'}, status=400)
        except ValueError as e:
            self._send_json({'error': str(e)}, status=400)
        except Exception as e:
            with _discovery_lock:
                _discovery_running = False
            self._send_json({'error': str(e)}, status=500)

    # ── Manual scrape trigger ─────────────────────────────────────────────

    def _run_scrape(self):
        """Trigger the driver (all workers) in a background thread."""
        global _scrape_running, _scrape_thread
        with _scrape_lock:
            if _scrape_running:
                self._send_json({'error': 'A scrape is already running. Please wait.'}, status=409)
                return
            _scrape_running = True

        def _bg_scrape():
            global _scrape_running
            try:
                # Force-reload config from disk so workers use the latest saved settings
                from core.config import reload as config_reload
                config_reload()
                from core.driver import run_all_workers
                run_all_workers()
            except Exception as e:
                import traceback
                traceback.print_exc()
            finally:
                with _scrape_lock:
                    _scrape_running = False

        _scrape_thread = threading.Thread(target=_bg_scrape, daemon=True)
        _scrape_thread.start()
        self._send_json({'status': 'started', 'message': 'Scrape started in background'})

    def _clear_data(self):
        """Delete all rows from the database tables and remove the CSV file."""
        try:
            import os
            from core.database import _get_conn, CSV_FILENAME
            from core.config import get_output_dir

            conn = _get_conn()
            try:
                conn.execute('DELETE FROM kpi_snapshots')
                conn.execute('DELETE FROM scrape_log')
                conn.commit()
            finally:
                conn.close()

            csv_path = os.path.join(get_output_dir(), CSV_FILENAME)
            if os.path.exists(csv_path):
                os.remove(csv_path)

            self._send_json({'status': 'ok', 'message': 'Database and CSV cleared'})
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

    # ── File serving ──────────────────────────────────────────────────────

    def _serve_file(self, filepath, content_type):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', f'{content_type}; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
        except FileNotFoundError:
            self.send_error(404, f'File not found: {filepath}')
        except Exception as e:
            self.send_error(500, str(e))

    def _serve_json_file(self, filepath):
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {}
            self._send_json(data)
        except json.JSONDecodeError:
            self._send_json({}, status=500)
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

    def _save_json_file(self, filepath):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(body)

            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            self._send_json({'status': 'ok'})
        except json.JSONDecodeError as e:
            self._send_json({'error': f'Invalid JSON: {e}'}, status=400)
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

    # ── Scrape log API ────────────────────────────────────────────────────

    def _serve_scrape_log(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            limit = int(qs.get('limit', ['100'])[0])
            log = get_scrape_log(limit)
            self._send_json(log)
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

    def _serve_scrape_status(self):
        try:
            status = get_latest_scrape_status()
            self._send_json(status)
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

    # ── Agent advisory APIs ───────────────────────────────────────────────

    def _serve_agent_insights(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            opts = parse_agent_query_params(qs)
            data = build_agent_insights(**opts)
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

    def _serve_agent_health_summary(self):
        try:
            self._send_json(build_health_summary())
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

    def _serve_agent_report(self, path: str):
        try:
            # Path format: /api/agent/report/<source>/<label>
            parts = path.split('/')
            if len(parts) < 6:
                self._send_json({'error': 'Invalid report path'}, status=400)
                return

            source = parts[4]
            label = '/'.join(parts[5:])

            qs = parse_qs(urlparse(self.path).query)
            lookback = int((qs.get('lookback') or ['500'])[0])
            include_evidence = (qs.get('include_evidence') or ['true'])[0].lower() in ('1', 'true', 'yes', 'on')

            data = build_report_insight(source, label, lookback=lookback, include_evidence=include_evidence)
            status = 400 if data.get('error') else 200
            self._send_json(data, status=status)
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _send_json(self, data, status=200):
        body = json.dumps(data, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Quieter logging — only show non-200 requests."""
        if len(args) >= 2 and '200' not in str(args[1]):
            super().log_message(format, *args)


def main():
    port = PORT
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:]):
            if arg == '--port' and i + 2 < len(sys.argv):
                port = int(sys.argv[i + 2])
            elif arg.isdigit():
                port = int(arg)

    # Ensure database exists (creates scrape_log table too)
    init_db()

    server = HTTPServer(('127.0.0.1', port), SettingsHandler)
    url = f'http://localhost:{port}'

    print(f'Data Aggregator Control Panel')
    print(f'  -> {url}')
    print(f'  Press Ctrl+C to stop\n')

    # Open browser after a short delay (let server start first)
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped.')
        server.server_close()


if __name__ == '__main__':
    main()
