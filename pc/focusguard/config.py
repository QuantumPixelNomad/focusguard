"""Configuration: defaults, validation, storage and password hashing."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets

from . import paths

YOUTUBE_CATEGORIES = [
    "Education", "Science & Technology", "Howto & Style", "News & Politics",
    "Nonprofits & Activism", "Film & Animation", "Autos & Vehicles", "Music",
    "Pets & Animals", "Sports", "Travel & Events", "Gaming", "People & Blogs",
    "Comedy", "Entertainment",
]
APP_CATEGORIES = {
    "games": "Games",
    "media": "Entertainment and media players",
    "chat": "Chat and messaging apps",
    "social": "Social media apps",
    "news": "News and feed readers",
}

DEFAULT = {
    "version": 1,
    "password": None,
    "apps": {"categories": [], "selected": [], "allowed": [], "custom_names": []},
    "web": {"categories": [], "custom_blocked": [], "exceptions": []},
    "youtube": {
        "mode": "filter",  # allow | filter | block
        "allowed_categories": ["Education", "Science & Technology"],
        "allow_keywords": [],
        "block_keywords": [],
        "unknown": "block",  # block | allow
        "block_shorts": True,
    },
    "schedules": [],
    "protection": {"strict": False, "require_extension": False, "harden_browsers": False},
    "session": None,
    "link": None,  # phone link, owned by the service: {"code": ..., "server": ...}
}

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z]{2,63}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def normalize_domain(text) -> str | None:
    """Turn user input such as 'https://www.Example.com/page' into 'example.com'."""
    if not isinstance(text, str):
        return None
    d = text.strip().lower()
    d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", d)
    d = re.split(r"[/?#\s]", d, maxsplit=1)[0]
    d = d.split("@")[-1].split(":")[0].strip(".")
    if d.startswith("www."):
        d = d[4:]
    try:
        d = d.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    return d if _DOMAIN_RE.match(d) else None


def _strs(value, limit=2000, maxlen=200) -> list[str]:
    out = []
    if isinstance(value, list):
        for v in value[:limit]:
            if isinstance(v, str) and v.strip() and "\n" not in v:
                out.append(v.strip()[:maxlen])
    return out


def _domains(value) -> list[str]:
    seen = []
    for v in _strs(value):
        d = normalize_domain(v)
        if d and d not in seen:
            seen.append(d)
    return seen


def sanitize(raw) -> dict:
    """Return a complete, well-typed config. Unknown or invalid values fall back to defaults.

    The password, session and link fields are never taken from here; the daemon owns them."""
    cfg = copy.deepcopy(DEFAULT)
    if not isinstance(raw, dict):
        return cfg

    apps = raw.get("apps") if isinstance(raw.get("apps"), dict) else {}
    cfg["apps"]["categories"] = [c for c in _strs(apps.get("categories")) if c in APP_CATEGORIES]
    cfg["apps"]["custom_names"] = [n for n in _strs(apps.get("custom_names"), maxlen=64) if "/" not in n]
    for key in ("selected", "allowed"):
        out = []
        for item in (apps.get(key) if isinstance(apps.get(key), list) else [])[:1000]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            out.append({
                "id": item["id"][:200],
                "name": str(item.get("name", item["id"]))[:200],
                "names": [n for n in _strs(item.get("names"), maxlen=64) if "/" not in n],
                "flatpak": str(item["flatpak"])[:200] if item.get("flatpak") else None,
                "snap": str(item["snap"])[:100] if item.get("snap") else None,
            })
        cfg["apps"][key] = out
    # An app ticked on its own is blocked, so it cannot also be an exception.
    picked = {a["id"] for a in cfg["apps"]["selected"]}
    cfg["apps"]["allowed"] = [a for a in cfg["apps"]["allowed"] if a["id"] not in picked]

    web = raw.get("web") if isinstance(raw.get("web"), dict) else {}
    cfg["web"]["categories"] = _strs(web.get("categories"), maxlen=40)
    cfg["web"]["custom_blocked"] = _domains(web.get("custom_blocked"))
    cfg["web"]["exceptions"] = _domains(web.get("exceptions"))

    yt = raw.get("youtube") if isinstance(raw.get("youtube"), dict) else {}
    if yt.get("mode") in ("allow", "filter", "block"):
        cfg["youtube"]["mode"] = yt["mode"]
    if isinstance(yt.get("allowed_categories"), list):
        cfg["youtube"]["allowed_categories"] = [c for c in _strs(yt["allowed_categories"]) if c in YOUTUBE_CATEGORIES]
    cfg["youtube"]["allow_keywords"] = [k.lower() for k in _strs(yt.get("allow_keywords"), maxlen=80)]
    cfg["youtube"]["block_keywords"] = [k.lower() for k in _strs(yt.get("block_keywords"), maxlen=80)]
    if yt.get("unknown") in ("block", "allow"):
        cfg["youtube"]["unknown"] = yt["unknown"]
    if isinstance(yt.get("block_shorts"), bool):
        cfg["youtube"]["block_shorts"] = yt["block_shorts"]

    schedules = []
    for item in (raw.get("schedules") if isinstance(raw.get("schedules"), list) else [])[:100]:
        if not isinstance(item, dict):
            continue
        start, end = item.get("start"), item.get("end")
        if not (isinstance(start, str) and isinstance(end, str) and _TIME_RE.match(start) and _TIME_RE.match(end)):
            continue
        days = sorted({d for d in item.get("days", []) if isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6}) \
            if isinstance(item.get("days"), list) else []
        schedules.append({
            "name": str(item.get("name", ""))[:80],
            "days": days,
            "start": start,
            "end": end,
            "enabled": bool(item.get("enabled", True)),
        })
    cfg["schedules"] = schedules

    prot = raw.get("protection") if isinstance(raw.get("protection"), dict) else {}
    for key in ("strict", "require_extension", "harden_browsers"):
        if isinstance(prot.get(key), bool):
            cfg["protection"][key] = prot[key]
    return cfg


def load() -> dict:
    try:
        with open(paths.CONFIG_FILE, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULT)
    cfg = sanitize(raw)
    pw = raw.get("password")
    if isinstance(pw, dict) and isinstance(pw.get("salt"), str) and isinstance(pw.get("hash"), str):
        cfg["password"] = {"salt": pw["salt"], "hash": pw["hash"]}
    sess = raw.get("session")
    if isinstance(sess, dict) and isinstance(sess.get("until"), (int, float)):
        cfg["session"] = {"until": float(sess["until"])}
    lnk = raw.get("link")
    if isinstance(lnk, dict) and isinstance(lnk.get("code"), str) and isinstance(lnk.get("server"), str):
        cfg["link"] = {"code": lnk["code"], "server": lnk["server"]}
    return cfg


def save(cfg: dict) -> None:
    os.makedirs(paths.CONFIG_DIR, mode=0o700, exist_ok=True)
    tmp = paths.CONFIG_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, paths.CONFIG_FILE)


def public_view(cfg: dict) -> dict:
    """The config as shown to the settings app: no password hash."""
    out = copy.deepcopy(cfg)
    out["has_password"] = bool(out.pop("password", None))
    return out


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def hash_password(password: str) -> dict:
    salt = secrets.token_bytes(16)
    return {"salt": salt.hex(), "hash": _scrypt(password, salt).hex()}


def verify_password(stored: dict | None, password) -> bool:
    if not stored:
        return True
    if not isinstance(password, str):
        return False
    try:
        expected = bytes.fromhex(stored["hash"])
        actual = _scrypt(password, bytes.fromhex(stored["salt"]))
    except (KeyError, ValueError):
        return False
    return hmac.compare_digest(expected, actual)
