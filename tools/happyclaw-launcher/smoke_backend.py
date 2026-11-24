"""Fake octop backend for launcher smoke test: /api/health with delayed agents."""
import http.server, json, os, time

START = time.monotonic()
DELAY = float(os.environ.get("FAKE_AGENT_DELAY", "2.5"))

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/health":
            agents = 1 if time.monotonic() - START >= DELAY else 0
            body = json.dumps({"ok": True, "agents_running": agents}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    port = int(os.environ.get("FAKE_PORT", "18097"))
    http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
