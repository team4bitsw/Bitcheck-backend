"""
Celery worker entrypoint for Cloud Run.

Cloud Run requires every container to respond on $PORT, so we spin up a
minimal HTTP health-check server on a background thread while the Celery
worker runs as the main process.
"""

import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, format, *args):
        pass  # silence access logs


def start_health_server(port: int) -> None:
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    health_thread = threading.Thread(target=start_health_server, args=(port,), daemon=True)
    health_thread.start()
    print(f'[worker] Health check listening on :{port}', flush=True)

    cmd = [
        sys.executable, '-m', 'celery',
        '-A', 'config.celery',
        'worker',
        '--loglevel=info',
        '--concurrency=2',
    ]
    print(f'[worker] Starting Celery: {" ".join(cmd)}', flush=True)
    result = subprocess.run(cmd)
    sys.exit(result.returncode)
