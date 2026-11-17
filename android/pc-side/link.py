"""Phone link: publishes the service's state, encrypted, to an ntfy topic the phone app reads.

Link protocol v1 (must match Relay.java in the Android app):

  link code  16 characters from ALPHABET, shown to the user as XXXX-XXXX-XXXX-XXXX
  master     HMAC-SHA256(key=b"focusguard-link-v1", code)
  topic      "fg" + first 40 hex characters of HMAC-SHA256(master, b"topic")
  key        HMAC-SHA256(master, b"enc")                       (AES-256-GCM)
  blob       12-byte nonce + AES-GCM(key, nonce, zlib(state JSON), aad=b"FG1")
  message    "FG1.<id>.<index>.<count>.<base64url piece of blob>", one HTTP POST per piece

The relay sees only the topic name and encrypted bytes. Needs the `cryptography` package
(python3-cryptography on Ubuntu).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time
import urllib.request
import zlib

ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
CODE_LENGTH = 16
DEFAULT_SERVER = "https://ntfy.sh"
PIECE_CHARS = 3000          # ntfy accepts 4096 bytes per message
REPUBLISH_SECONDS = 3 * 3600  # ntfy.sh keeps messages for 12 hours
MIN_GAP_SECONDS = 5           # at most one publish per this many seconds


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def normalize_code(text) -> str | None:
    if not isinstance(text, str):
        return None
    code = text.upper().replace("-", "").replace(" ", "")
    return code if len(code) == CODE_LENGTH and all(c in ALPHABET for c in code) else None


def _master(code: str) -> bytes:
    return hmac.new(b"focusguard-link-v1", code.encode("ascii"), hashlib.sha256).digest()


def topic(code: str) -> str:
    return "fg" + hmac.new(_master(code), b"topic", hashlib.sha256).hexdigest()[:40]


def key(code: str) -> bytes:
    return hmac.new(_master(code), b"enc", hashlib.sha256).digest()


def available() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        return True
    except Exception:
        return False


def seal(code: str, state: dict) -> list[str]:
    """Encrypt a state and return the message bodies to post, in order."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    packed = zlib.compress(json.dumps(state, separators=(",", ":")).encode("utf-8"), 9)
    nonce = os.urandom(12)
    blob = nonce + AESGCM(key(code)).encrypt(nonce, packed, b"FG1")
    text = base64.urlsafe_b64encode(blob).decode("ascii")
    pieces = [text[i:i + PIECE_CHARS] for i in range(0, len(text), PIECE_CHARS)]
    msg_id = secrets.token_hex(4)
    return [f"FG1.{msg_id}.{i}.{len(pieces)}.{p}" for i, p in enumerate(pieces)]


def build_state(cfg: dict, now: float | None = None) -> dict:
    """What the phone needs from the service's config. No password, no PC app list."""
    session = cfg.get("session")
    return {
        "v": 1,
        "name": socket.gethostname(),
        "now": time.time() if now is None else now,
        "session_until": session["until"] if session else None,
        "schedules": cfg["schedules"],
        "app_categories": cfg["apps"]["categories"],
        "web_categories": cfg["web"]["categories"],
        "custom_blocked": cfg["web"]["custom_blocked"],
        "exceptions": cfg["web"]["exceptions"],
        "youtube_mode": cfg["youtube"]["mode"],
        "strict": cfg["protection"]["strict"],
    }


def _fingerprint(state: dict) -> str:
    return json.dumps({k: v for k, v in state.items() if k != "now"}, sort_keys=True)


class Publisher:
    """Background thread that posts the state whenever it changes, and every few hours.

    get_link() returns {"code": str, "server": str} or None when no phone is linked.
    get_state() returns build_state(...) for the present config.
    """

    def __init__(self, get_link, get_state, log=lambda message: None):
        self.get_link, self.get_state, self.log = get_link, get_state, log
        self.wake = threading.Event()
        self.stop_flag = threading.Event()
        self.last_fingerprint = None
        self.last_publish = 0.0
        self.last_ok: float | None = None
        self.last_error: str | None = None
        self.retry_delay = 0

    def start(self) -> None:
        threading.Thread(target=self.run, daemon=True, name="focusguard-link").start()

    def notify(self) -> None:
        """Call after anything that may have changed the state."""
        self.wake.set()

    def status(self) -> dict:
        return {"available": available(), "last_ok": self.last_ok, "last_error": self.last_error}

    def run(self) -> None:
        while not self.stop_flag.is_set():
            self.wake.wait(self.retry_delay or 20)
            self.wake.clear()
            if self.stop_flag.is_set():
                break
            try:
                self.step()
            except Exception as exc:  # never let the thread die
                self.last_error = repr(exc)

    def step(self) -> bool:
        """Publish if needed. Returns True if something was sent."""
        link = self.get_link()
        if not link or not normalize_code(link.get("code")):
            self.last_fingerprint = None
            return False
        if not available():
            self.last_error = "The python3-cryptography package is not installed."
            return False
        state = self.get_state()
        fingerprint = link["code"] + _fingerprint(state)
        now = time.time()
        due = fingerprint != self.last_fingerprint or now - self.last_publish >= REPUBLISH_SECONDS
        if not due:
            return False
        if now - self.last_publish < MIN_GAP_SECONDS:
            self.retry_delay = MIN_GAP_SECONDS
            return False
        self.last_publish = now
        server = (link.get("server") or DEFAULT_SERVER).rstrip("/")
        try:
            for body in seal(link["code"], state):
                req = urllib.request.Request(
                    f"{server}/{topic(link['code'])}", data=body.encode("ascii"), method="POST",
                    headers={"Content-Type": "text/plain", "User-Agent": "FocusGuard"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    resp.read()
        except Exception as exc:
            if self.last_error is None:
                self.log(f"Could not reach the phone relay: {exc}")
            self.last_error = str(exc)
            self.retry_delay = min(max(self.retry_delay * 2, 30), 900)
            return False
        self.last_fingerprint = fingerprint
        self.last_ok, self.last_error, self.retry_delay = now, None, 0
        return True
