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

PORT = 8580
UI_FILE = os.path.join(PROJECT_ROOT, 'ui', 'settings.html')


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
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/api/settings':
            self._save_json_file(SETTINGS_PATH)
        elif path == '/api/credentials':
            self._save_json_file(CREDENTIALS_PATH)
        else:
            self.send_error(404)

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
    print(f'  → {url}')
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
