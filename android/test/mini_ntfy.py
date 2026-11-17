"""A stand-in for ntfy.sh: POST /<topic> stores a message, GET /<topic>/json?since=all[&poll=1] returns them and keeps streaming."""
import json, sys, threading, time, secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

messages, cond = {}, threading.Condition()

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_POST(self):
        topic = self.path.strip("/")
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        if len(body) > 4096:
            self.send_response(413); self.send_header("Content-Length", "0"); self.end_headers(); return
        m = {"id": secrets.token_hex(6), "time": int(time.time()), "event": "message", "topic": topic, "message": body}
        with cond:
            messages.setdefault(topic, []).append(m); cond.notify_all()
        data = json.dumps(m).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        u = urlparse(self.path); parts = u.path.strip("/").split("/")
        if len(parts) != 2 or parts[1] != "json":
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        topic, poll = parts[0], "poll" in parse_qs(u.query)
        self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.send_header("Connection", "close"); self.end_headers()
        def line(o): self.wfile.write((json.dumps(o) + "\n").encode()); self.wfile.flush()
        sent = 0
        try:
            line({"id": "o", "time": int(time.time()), "event": "open", "topic": topic})
            while True:
                with cond:
                    pending = messages.get(topic, [])[sent:]
                    if not pending and not poll:
                        cond.wait(2)
                        pending = messages.get(topic, [])[sent:]
                for m in pending: line(m)
                sent += len(pending)
                if poll: break
                if not pending: line({"id": "k", "time": int(time.time()), "event": "keepalive", "topic": topic})
        except OSError:
            pass
        self.close_connection = True

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
