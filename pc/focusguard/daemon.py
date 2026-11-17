"""The FocusGuard background service. Runs as root; enforces the blocks."""
from __future__ import annotations

import copy
import json
import os
import signal
import socketserver
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, apps, config, link, paths, schedule, system

TICK_SECONDS = 3
HEARTBEAT_TTL = 150       # seconds an extension check-in stays valid
BROWSER_GRACE = 90        # seconds a browser may run before its extension must have checked in
YOUTUBE_DOMAINS = {"youtube.com", "youtu.be", "youtube-nocookie.com"}
BROWSER_LABELS = {"firefox": "Firefox", "chrome": "Google Chrome", "chromium": "Chromium", "brave": "Brave",
                  "edge": "Microsoft Edge", "opera": "Opera", "unsupported": "an unsupported browser"}


def load_web_categories() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "web_categories.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Daemon:
    def __init__(self):
        self.lock = threading.RLock()
        self.cfg = config.load()
        self.web_categories = load_web_categories()
        self.heartbeats: dict[str, float] = {}
        self.events: deque = deque(maxlen=40)
        self.event_seq = 0
        self.was_active = None
        self.installed_apps: list = []
        self.installed_at = 0.0
        self.termed: dict[int, float] = {}
        self.last_notice: dict[str, float] = {}
        self.last_slow = 0.0
        self.immutable = None
        self.policies = None
        self.stop_flag = threading.Event()
        self.publisher = link.Publisher(self._link, self._link_state, self.log)

    def _link(self):
        with self.lock:
            return copy.deepcopy(self.cfg.get("link"))

    def _link_state(self) -> dict:
        with self.lock:
            return link.build_state(copy.deepcopy(self.cfg))

    # ---- state -----------------------------------------------------------------
    def log(self, message: str) -> None:
        with self.lock:
            self.event_seq += 1
            self.events.append({"seq": self.event_seq, "time": time.time(), "message": message})

    def notice(self, key: str, message: str, every: float = 60) -> None:
        now = time.time()
        if now - self.last_notice.get(key, 0) >= every:
            self.last_notice[key] = now
            self.log(message)

    def active_info(self):
        """(active, until_epoch, reason) for the present moment."""
        with self.lock:
            now = datetime.now()
            until, reason = None, None
            sched_until = schedule.active_until(self.cfg["schedules"], now)
            if sched_until:
                until, reason = sched_until.timestamp(), "schedule"
            sess = self.cfg.get("session")
            if sess and sess["until"] > time.time():
                if until is None or sess["until"] > until:
                    until = sess["until"]
                reason = "schedule and session" if reason else "session"
            return (until is not None), until, reason

    def locked(self) -> bool:
        return bool(self.cfg["protection"]["strict"] and self.active_info()[0])

    def blocked_domains(self) -> list[str]:
        web, yt_mode = self.cfg["web"], self.cfg["youtube"]["mode"]
        domains = set(web["custom_blocked"])
        for cat in web["categories"]:
            domains.update(self.web_categories.get(cat, {}).get("domains", []))
        if yt_mode == "block":
            domains |= YOUTUBE_DOMAINS
        else:
            domains -= YOUTUBE_DOMAINS
        return sorted(domains - set(web["exceptions"]))

    def web_rules_exist(self) -> bool:
        return bool(self.blocked_domains()) or self.cfg["youtube"]["mode"] != "allow"

    def policy(self) -> dict:
        with self.lock:
            active, until, _ = self.active_info()
            return {
                "active": active,
                "until": until,
                "blocked_domains": self.blocked_domains() if active else [],
                "exceptions": self.cfg["web"]["exceptions"],
                "youtube": self.cfg["youtube"],
            }

    def status(self) -> dict:
        with self.lock:
            active, until, reason = self.active_info()
            nxt = schedule.next_start(self.cfg["schedules"], datetime.now())
            now = time.time()
            return {
                "version": __version__,
                "active": active,
                "until": until,
                "reason": reason,
                "next_start": nxt.timestamp() if nxt else None,
                "strict": self.cfg["protection"]["strict"],
                "locked": self.locked(),
                "has_password": bool(self.cfg["password"]),
                "extensions": {b: round(now - t) for b, t in self.heartbeats.items() if now - t < HEARTBEAT_TTL},
                "events": list(self.events),
                "phone_link": dict(self.publisher.status(), linked=bool(self.cfg.get("link"))),
            }

    # ---- control commands -----------------------------------------------------
    def handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "status":
            return {"ok": True, "status": self.status()}
        if cmd == "get_config":
            with self.lock:
                return {"ok": True, "config": config.public_view(self.cfg),
                        "web_categories": {k: {"label": v["label"], "count": len(v["domains"])}
                                           for k, v in self.web_categories.items()}}
        if cmd == "start_session":
            minutes = req.get("minutes")
            if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or not 1 <= minutes <= 7 * 24 * 60:
                return {"ok": False, "error": "Session length must be between 1 minute and 7 days."}
            with self.lock:
                until = time.time() + minutes * 60
                current = (self.cfg.get("session") or {}).get("until", 0)
                self.cfg["session"] = {"until": max(until, current)}  # a session can only be extended
                self._save()
            self.log(f"Focus session started for {int(minutes)} minutes.")
            self.publisher.notify()
            return {"ok": True}
        if cmd not in ("stop_session", "set_config", "set_password", "prepare_uninstall", "check_password",
                       "link_create", "link_remove"):
            return {"ok": False, "error": "Unknown command."}

        # Everything below weakens or changes the blocker, so it is gated.
        if cmd != "check_password" and self.locked():
            return {"ok": False, "error": "locked",
                    "message": "Strict mode is on and a block is running. Nothing can be changed until it ends."}
        with self.lock:
            stored = copy.deepcopy(self.cfg["password"])
        if not config.verify_password(stored, req.get("password")):
            time.sleep(1.5)  # slow down guessing
            return {"ok": False, "error": "password", "message": "Wrong password."}

        with self.lock:
            if cmd == "check_password":
                return {"ok": True}
            self.publisher.notify()  # every command below may change what the phone should see
            if cmd == "link_create":
                server = os.environ.get("FOCUSGUARD_LINK_SERVER") or link.DEFAULT_SERVER
                self.cfg["link"] = {"code": link.new_code(), "server": server}
                self._save()
                self.log("Phone link created.")
                return {"ok": True, "code": self.cfg["link"]["code"]}
            if cmd == "link_remove":
                self.cfg["link"] = None
                self._save()
                self.log("Phone link removed.")
                return {"ok": True}
            if cmd == "stop_session":
                self.cfg["session"] = None
                self._save()
                self.log("Focus session ended early.")
                return {"ok": True}
            if cmd == "set_config":
                new = config.sanitize(req.get("config"))
                new["password"], new["session"] = self.cfg["password"], self.cfg["session"]
                new["link"] = self.cfg.get("link")
                self.cfg = new
                self._save()
                self.installed_at = 0
                return {"ok": True, "config": config.public_view(self.cfg)}
            if cmd == "set_password":
                new_pw = req.get("new_password")
                if new_pw is not None and not isinstance(new_pw, str):
                    return {"ok": False, "error": "Invalid password."}
                self.cfg["password"] = config.hash_password(new_pw) if new_pw else None
                self._save()
                self.log("Password changed." if new_pw else "Password removed.")
                return {"ok": True}
            if cmd == "prepare_uninstall":
                system.set_immutable(False)
                self.immutable = False
                system.apply_hosts([])
                system.apply_browser_policies(False)
                with open(paths.UNINSTALL_TOKEN, "w") as fh:
                    fh.write(str(time.time()))
                return {"ok": True}
        return {"ok": False, "error": "Unknown command."}

    def _save(self) -> None:
        if self.immutable:
            system.set_immutable(False)
            self.immutable = False
        config.save(self.cfg)

    # ---- enforcement ----------------------------------------------------------
    def tick(self) -> None:
        with self.lock:
            cfg = copy.deepcopy(self.cfg)
            active, _, _ = self.active_info()
            domains = self.blocked_domains() if active else []
            if cfg.get("session") and cfg["session"]["until"] <= time.time():
                self.cfg["session"] = None
                self._save()
                self.publisher.notify()
        if self.was_active is not None and active != self.was_active:
            self.log("Blocking is now on." if active else "Blocking has ended.")
        self.was_active = active

        if system.apply_hosts(domains) and domains:
            self.notice("hosts", "Website block list applied.", every=300)

        if active:
            procs = list(apps.iter_procs())
            alive = self._enforce_apps(cfg, procs)
            if cfg["protection"]["require_extension"] and (domains or cfg["youtube"]["mode"] != "allow"):
                alive |= self._enforce_browsers(procs)
            for pid in list(self.termed):
                if pid not in alive:
                    del self.termed[pid]
        else:
            self.termed.clear()

        now = time.time()
        if now - self.last_slow >= 30:
            self.last_slow = now
            want_policies = cfg["protection"]["harden_browsers"]
            if want_policies or self.policies is not False:
                system.apply_browser_policies(want_policies)
                self.policies = want_policies
            want_immutable = bool(active and cfg["protection"]["strict"])
            if want_immutable or self.immutable is not False:
                system.set_immutable(want_immutable)
                self.immutable = want_immutable
            system.ensure_watchdog()

    def _installed(self) -> list:
        if time.time() - self.installed_at > 120:
            self.installed_apps = apps.scan_apps()
            self.installed_at = time.time()
        return self.installed_apps

    def _kill(self, proc, label: str, key: str, message: str) -> None:
        first = self.termed.get(proc.pid)
        try:
            if first is None:
                os.kill(proc.pid, signal.SIGTERM)
                self.termed[proc.pid] = time.time()
                self.notice(key, message)
            elif time.time() - first > 4:
                os.kill(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def _enforce_apps(self, cfg, procs) -> set:
        matcher = apps.build_matcher(cfg["apps"], self._installed())
        alive = set()
        if not matcher.empty():
            for proc in procs:
                label = matcher.match(proc)
                if label:
                    alive.add(proc.pid)
                    self._kill(proc, label, "app:" + label, f"Closed {label}: it is blocked right now.")
        return alive

    def _enforce_browsers(self, procs) -> set:
        now = time.time()
        with self.lock:
            fresh = {b for b, t in self.heartbeats.items() if now - t < HEARTBEAT_TTL}
        alive = set()
        for proc in procs:
            family = apps.browser_family(proc)
            if not family or family in fresh:
                continue
            if family != "unsupported" and proc.age() < BROWSER_GRACE:
                continue
            alive.add(proc.pid)
            label = BROWSER_LABELS.get(family, family)
            self._kill(proc, label, "browser:" + family,
                       f"Closed {label}: the FocusGuard extension is not running in it.")
        return alive

    def run(self) -> None:
        while not self.stop_flag.is_set():
            try:
                self.tick()
            except Exception as exc:  # the enforcement loop must never die
                print(f"focusguard: tick failed: {exc!r}", file=sys.stderr, flush=True)
            self.stop_flag.wait(TICK_SECONDS)


# ---- control socket (settings app and CLI) -----------------------------------
class ControlHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline(4 * 1024 * 1024)
            req = json.loads(line.decode("utf-8"))
            if not isinstance(req, dict):
                raise ValueError
            resp = self.server.daemon.handle(req)
        except (ValueError, UnicodeDecodeError):
            resp = {"ok": False, "error": "Malformed request."}
        except Exception as exc:
            resp = {"ok": False, "error": f"Internal error: {exc!r}"}
        try:
            self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))
        except OSError:
            pass


class ControlServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


# ---- HTTP endpoint (browser extension) ---------------------------------------
def _extension_origin(origin: str | None) -> bool:
    return bool(origin) and origin.startswith(("moz-extension://", "chrome-extension://"))


class ExtensionHandler(BaseHTTPRequestHandler):
    server_version = "FocusGuard"

    def log_message(self, *args):
        pass

    def _reply(self, code: int, body: dict | None = None):
        data = json.dumps(body or {}).encode("utf-8")
        self.send_response(code)
        origin = self.headers.get("Origin")
        if _extension_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _web_page(self) -> bool:
        """Requests from ordinary web pages carry an http(s) Origin; refuse those."""
        origin = self.headers.get("Origin")
        return bool(origin) and not _extension_origin(origin)

    def do_OPTIONS(self):
        self._reply(403 if self._web_page() else 204)

    def do_GET(self):
        if self._web_page():
            return self._reply(403)
        if self.path.split("?")[0] == "/policy":
            return self._reply(200, self.server.daemon.policy())
        self._reply(404)

    def do_POST(self):
        if self._web_page():
            return self._reply(403)
        if self.path != "/heartbeat":
            return self._reply(404)
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 4096)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            browser = body.get("browser")
        except (ValueError, AttributeError, UnicodeDecodeError):
            return self._reply(400)
        if browser in ("firefox", "chrome", "chromium", "brave", "edge", "opera"):
            d = self.server.daemon
            with d.lock:
                d.heartbeats[browser] = time.time()
        self._reply(200, self.server.daemon.policy())


def main() -> int:
    if os.geteuid() != 0 and not paths.TEST_MODE:
        print("focusguardd must run as root (it is started by systemd).", file=sys.stderr)
        return 1
    os.makedirs(paths.RUN_DIR, mode=0o755, exist_ok=True)
    os.makedirs(paths.CONFIG_DIR, mode=0o700, exist_ok=True)
    for stale in (paths.SOCKET, paths.UNINSTALL_TOKEN):
        try:
            os.unlink(stale)
        except OSError:
            pass
    daemon = Daemon()

    control = ControlServer(paths.SOCKET, ControlHandler)
    control.daemon = daemon
    os.chmod(paths.SOCKET, 0o666)
    threading.Thread(target=control.serve_forever, daemon=True).start()

    try:
        http = ThreadingHTTPServer((paths.HTTP_HOST, paths.HTTP_PORT), ExtensionHandler)
        http.daemon_threads = True
        http.daemon = daemon
        threading.Thread(target=http.serve_forever, daemon=True).start()
    except OSError as exc:
        print(f"focusguard: cannot listen for the browser extension: {exc}", file=sys.stderr, flush=True)

    signal.signal(signal.SIGTERM, lambda *_: daemon.stop_flag.set())
    signal.signal(signal.SIGINT, lambda *_: daemon.stop_flag.set())
    daemon.publisher.start()
    daemon.log("FocusGuard service started.")
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
