"""File locations. FOCUSGUARD_ROOT relocates everything for tests."""
from __future__ import annotations

import os

ROOT = os.environ.get("FOCUSGUARD_ROOT", "")
TEST_MODE = bool(ROOT)


def _p(path: str) -> str:
    return ROOT + path if ROOT else path


CONFIG_DIR = _p("/etc/focusguard")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
RUN_DIR = _p("/run/focusguard")
SOCKET = os.path.join(RUN_DIR, "control.sock")
UNINSTALL_TOKEN = os.path.join(RUN_DIR, "uninstall-ok")
HOSTS_FILE = _p("/etc/hosts")
INSTALL_DIR = "/opt/focusguard"
UNIT_FILES = [
    "/etc/systemd/system/focusguard.service",
    "/etc/systemd/system/focusguard-watchdog.service",
    "/etc/systemd/system/focusguard-watchdog.timer",
]
HTTP_HOST = "127.0.0.1"
HTTP_PORT = int(os.environ.get("FOCUSGUARD_PORT", "47613"))

FIREFOX_POLICY = _p("/etc/firefox/policies/policies.json")
CHROMIUM_POLICY_DIRS = [
    _p("/etc/opt/chrome/policies/managed"),
    _p("/etc/chromium/policies/managed"),
    _p("/etc/chromium-browser/policies/managed"),
    _p("/etc/brave/policies/managed"),
    _p("/etc/opt/edge/policies/managed"),
]
