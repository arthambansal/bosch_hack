"""Zero-dependency dashboard server: serves dashboard/index.html and /state (= runs/live_state.json)."""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "runs", "live_state.json")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = STATE if self.path.startswith("/state") else os.path.join(HERE, "index.html")
        ctype = "application/json" if path == STATE else "text/html; charset=utf-8"
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            body, ctype = (b"{}" if path == STATE else b"dashboard/index.html not found"), "text/plain"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):   # keep the terminal quiet
        pass


if __name__ == "__main__":
    print("Dashboard: http://localhost:8000  (Ctrl+C to stop)")
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
