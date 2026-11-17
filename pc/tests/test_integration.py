"""Runs the real service in a sandbox directory and drives it like the app and extension do.

Needs root (to start a stand-in "game" under an ordinary user id); skipped otherwise."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ROOT = tempfile.mkdtemp(prefix="focusguard-it-")
PORT = "47699"
os.environ["FOCUSGUARD_ROOT"] = ROOT
os.environ["FOCUSGUARD_PORT"] = PORT
sys.path.insert(0, REPO)

import importlib  # noqa: E402

from focusguard import client, paths  # noqa: E402


def http(path, data=None, origin=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, {}


def wait_for(predicate, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.3)
    return False


@unittest.skipUnless(os.geteuid() == 0 and shutil.which("setpriv"), "needs root and setpriv")
class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.update(FOCUSGUARD_ROOT=ROOT, FOCUSGUARD_PORT=PORT)
        importlib.reload(paths)
        os.makedirs(os.path.join(ROOT, "etc"), exist_ok=True)
        with open(paths.HOSTS_FILE, "w") as fh:
            fh.write("127.0.0.1 localhost\n")
        import http.server
        import threading

        class Relay(http.server.BaseHTTPRequestHandler):
            posts = []

            def do_POST(self):
                self.posts.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        cls.relay = Relay
        cls.relay_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Relay)
        threading.Thread(target=cls.relay_server.serve_forever, daemon=True).start()
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        os.environ["FOCUSGUARD_LINK_SERVER"] = f"http://127.0.0.1:{cls.relay_server.server_address[1]}"
        env = dict(os.environ, PYTHONPATH=REPO)
        cls.daemon = subprocess.Popen([sys.executable, "-m", "focusguard.daemon"], env=env)
        cls.addClassCleanup(lambda: cls.daemon.poll() is None and cls.daemon.kill())
        assert wait_for(lambda: os.path.exists(paths.SOCKET)), "service did not start"
        cls.bindir = tempfile.mkdtemp(prefix="fg-bin-")
        os.chmod(cls.bindir, 0o755)
        for name in ("fakegame", "harmless"):
            shutil.copy("/bin/sleep", os.path.join(cls.bindir, name))
        cls.children = []

    @classmethod
    def tearDownClass(cls):
        cls.daemon.terminate()
        cls.daemon.wait(10)
        for c in cls.children:
            if c.poll() is None:
                c.kill()
        shutil.rmtree(ROOT, ignore_errors=True)

    def spawn(self, name):
        proc = subprocess.Popen(["setpriv", "--reuid", "1234", "--regid", "1234", "--clear-groups",
                                 os.path.join(self.bindir, name), "600"])
        self.children.append(proc)
        return proc

    def hosts(self):
        with open(paths.HOSTS_FILE) as fh:
            return fh.read()

    def check_phone_link(self):
        from focusguard import link
        call = client.call
        self.assertFalse(call("status")["status"]["phone_link"]["linked"])
        self.assertEqual(self.relay.posts, [], "nothing may be sent before a phone is linked")
        resp = call("link_create")
        self.assertTrue(resp["ok"], resp)
        code = resp["code"]
        self.assertEqual(link.normalize_code(code), code)
        self.assertEqual(call("get_config")["config"]["link"]["code"], code)
        if not link.available():
            self.assertTrue(wait_for(lambda: call("status")["status"]["phone_link"]["last_error"], 30))
            return
        self.assertTrue(wait_for(lambda: self.relay.posts, 40), "state was not published")
        self.assertTrue(wait_for(lambda: call("status")["status"]["phone_link"]["last_ok"], 10))
        path, body = self.relay.posts[-1]
        self.assertEqual(path, "/" + link.topic(code))
        self.assertNotIn(b"reddit", body)  # encrypted on the wire
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import base64, zlib
        tag, _id, index, count, piece = body.decode().split(".", 4)
        self.assertEqual((tag, index, count), ("FG1", "0", "1"))
        blob = base64.urlsafe_b64decode(piece)
        state = json.loads(zlib.decompress(AESGCM(link.key(code)).decrypt(blob[:12], blob[12:], b"FG1")))
        self.assertEqual(state["web_categories"], ["social"])
        self.assertGreater(state["session_until"], time.time())
        # set_config must not be able to change or drop the link.
        cfg = call("get_config")["config"]
        cfg["link"] = {"code": "A" * 16, "server": "http://evil.example"}
        self.assertTrue(call("set_config", config=cfg)["ok"])
        self.assertEqual(call("get_config")["config"]["link"]["code"], code)
        before = len(self.relay.posts)
        self.assertTrue(call("link_remove")["ok"])
        self.assertIsNone(call("get_config")["config"]["link"])
        time.sleep(8)
        self.assertEqual(len(self.relay.posts), before, "nothing may be sent after unlinking")

    def test_full_flow(self):
        call = client.call
        st = call("status")["status"]
        self.assertFalse(st["active"])

        # Configure: block a custom app name, the social category, one custom site, with an exception.
        cfg = {"apps": {"custom_names": ["fakegame"]},
               "web": {"categories": ["social"], "custom_blocked": ["https://www.example.org/x"],
                       "exceptions": ["linkedin.com"]},
               "youtube": {"mode": "filter"}, "schedules": [], "protection": {"strict": False}}
        resp = call("set_config", config=cfg)
        self.assertTrue(resp["ok"], resp)
        self.assertEqual(resp["config"]["web"]["custom_blocked"], ["example.org"])

        game, other = self.spawn("fakegame"), self.spawn("harmless")
        time.sleep(4)
        self.assertIsNone(game.poll(), "nothing may be closed while blocking is off")
        self.assertNotIn("FocusGuard", self.hosts())
        self.assertEqual(http("/policy")[1]["blocked_domains"], [])

        # Start a session: the app is closed, hosts get the block, the extension sees the policy.
        self.assertTrue(call("start_session", minutes=30)["ok"])
        self.assertTrue(wait_for(lambda: game.poll() is not None), "blocked app was not closed")
        self.assertIsNone(other.poll(), "an unrelated program was closed")
        text = self.hosts()
        for needle in ("0.0.0.0 reddit.com", "0.0.0.0 www.example.org", "127.0.0.1 localhost"):
            self.assertIn(needle, text)
        self.assertNotIn("linkedin.com", text)
        self.assertNotIn("youtube.com", text)  # filtered by the extension, not blocked outright

        code, policy = http("/heartbeat", {"browser": "firefox"}, origin="moz-extension://abc")
        self.assertEqual(code, 200)
        self.assertTrue(policy["active"])
        self.assertIn("reddit.com", policy["blocked_domains"])
        self.assertEqual(policy["youtube"]["mode"], "filter")
        self.assertIn("firefox", call("status")["status"]["extensions"])
        # Ordinary web pages must not be able to read the policy or fake a heartbeat.
        self.assertEqual(http("/policy", origin="https://evil.example")[0], 403)
        self.assertEqual(http("/heartbeat", {"browser": "chrome"}, origin="https://evil.example")[0], 403)
        self.assertNotIn("chrome", call("status")["status"]["extensions"])

        # Tampering with the hosts file is undone.
        with open(paths.HOSTS_FILE, "w") as fh:
            fh.write("127.0.0.1 localhost\n")
        self.assertTrue(wait_for(lambda: "reddit.com" in self.hosts()), "hosts block was not restored")

        # A relaunched blocked app is closed again.
        again = self.spawn("fakegame")
        self.assertTrue(wait_for(lambda: again.poll() is not None))

        # Phone link: the state is published encrypted to the relay (a local stand-in here).
        self.check_phone_link()

        # Password protection.
        self.assertTrue(call("set_password", new_password="hunter2")["ok"])
        self.assertEqual(call("stop_session")["error"], "password")
        self.assertEqual(call("stop_session", password="nope")["error"], "password")
        self.assertEqual(call("set_config", config={}, password="nope")["error"], "password")
        self.assertEqual(call("set_password", new_password=None)["error"], "password")
        self.assertEqual(call("prepare_uninstall")["error"], "password")
        self.assertTrue(call("status")["status"]["active"])
        self.assertNotIn("password", call("get_config")["config"])
        with open(paths.CONFIG_FILE) as fh:
            self.assertNotIn("hunter2", fh.read())

        # Strict mode: locked even with the right password, until the block ends.
        cfg["protection"]["strict"] = True
        self.assertTrue(call("set_config", config=cfg, password="hunter2")["ok"])
        self.assertTrue(call("status")["status"]["locked"])
        for cmd, extra in (("stop_session", {}), ("set_config", {"config": {}}),
                           ("set_password", {"new_password": None}), ("prepare_uninstall", {})):
            self.assertEqual(call(cmd, password="hunter2", **extra)["error"], "locked", cmd)
        self.assertFalse(os.path.exists(paths.UNINSTALL_TOKEN))
        self.assertTrue(call("start_session", minutes=5)["ok"])  # extending is always allowed

        # Kill the service mid-block and restart it: the block survives.
        self.daemon.kill()
        self.daemon.wait(10)
        type(self).daemon = subprocess.Popen([sys.executable, "-m", "focusguard.daemon"],
                                             env=dict(os.environ, PYTHONPATH=REPO))
        self.assertTrue(wait_for(lambda: os.path.exists(paths.SOCKET)))
        def active():
            try:
                return call("status")["status"]["active"]
            except client.ServiceError:
                return False
        self.assertTrue(wait_for(active), "block did not survive a restart")

        # End the block by hand-editing nothing: simulate expiry by rewriting the stored end time.
        self.daemon.terminate()
        self.daemon.wait(10)
        with open(paths.CONFIG_FILE) as fh:
            stored = json.load(fh)
        stored["session"] = {"until": time.time() - 1}
        with open(paths.CONFIG_FILE, "w") as fh:
            json.dump(stored, fh)
        type(self).daemon = subprocess.Popen([sys.executable, "-m", "focusguard.daemon"],
                                             env=dict(os.environ, PYTHONPATH=REPO))
        self.assertTrue(wait_for(lambda: os.path.exists(paths.SOCKET)))
        self.assertTrue(wait_for(lambda: "FocusGuard" not in self.hosts()), "hosts block not removed after the block")
        st = call("status")["status"]
        self.assertFalse(st["active"])
        self.assertFalse(st["locked"])
        self.assertEqual(self.hosts(), "127.0.0.1 localhost\n")

        # Now unlocked: the password works again, and uninstall can be prepared.
        self.assertTrue(call("check_password", password="hunter2")["ok"])
        self.assertTrue(call("prepare_uninstall", password="hunter2")["ok"])
        self.assertTrue(os.path.exists(paths.UNINSTALL_TOKEN))


if __name__ == "__main__":
    unittest.main()
