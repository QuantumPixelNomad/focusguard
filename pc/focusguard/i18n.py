"""Interface language for the settings window: English or Arabic (right to left).

The choice is a per-user preference kept in ~/.config/focusguard/gui.json; the service and the
command-line tool stay in English. Translations are looked up by the English text itself."""
from __future__ import annotations

import json
import os
import re

from .lang_ar import AR

LANGUAGES = {"en": "English", "ar": "العربية"}
_current = "en"


def pref_file() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "focusguard", "gui.json")


def load_language() -> str:
    try:
        with open(pref_file(), encoding="utf-8") as fh:
            lang = json.load(fh).get("language")
    except (OSError, ValueError, AttributeError):
        lang = None
    return lang if lang in LANGUAGES else "en"


def save_language(lang: str) -> None:
    path = pref_file()
    data = {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        pass
    if not isinstance(data, dict):
        data = {}
    data["language"] = lang
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in LANGUAGES else "en"


def language() -> str:
    return _current


def is_rtl() -> bool:
    return _current == "ar"


def _(text: str) -> str:
    if _current == "ar":
        return AR.get(text, text)
    return text


# Messages that come from the service in English, translated for display.
_PATTERNS = [
    (re.compile(r"^Closed (.+): it is blocked right now\.$"), "Closed {0}: it is blocked right now."),
    (re.compile(r"^Closed (.+): the FocusGuard extension is not running in it\.$"),
     "Closed {0}: the FocusGuard extension is not running in it."),
    (re.compile(r"^Focus session started for (\d+) minutes\.$"), "Focus session started for {0} minutes."),
    (re.compile(r"^The FocusGuard service is not reachable \((.*)\)\.$"), "The FocusGuard service is not reachable ({0})."),
]


def tr_message(text: str) -> str:
    if _current != "ar" or not text:
        return text
    if text in AR:
        return AR[text]
    for rx, key in _PATTERNS:
        m = rx.match(text)
        if m and key in AR:
            return AR[key].format(*m.groups())
    return text
