"""System-level enforcement helpers: hosts file, browser policies, immutable flags, systemd."""
from __future__ import annotations

import json
import os
import subprocess

from . import paths

BEGIN = "# >>> FocusGuard: managed block, do not edit >>>"
END = "# <<< FocusGuard <<<"


def _hosts_section(domains) -> str:
    lines = [BEGIN]
    for d in sorted(set(domains)):
        names = [d] if d.startswith("www.") else [d, "www." + d]
        for n in names:
            lines.append(f"0.0.0.0 {n}")
            lines.append(f":: {n}")
    lines.append(END)
    return "\n".join(lines) + "\n"


def strip_hosts_section(text: str) -> str:
    out, skipping = [], False
    for line in text.splitlines():
        if line.strip() == BEGIN:
            skipping = True
        elif line.strip() == END:
            skipping = False
        elif not skipping:
            out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def apply_hosts(domains) -> bool:
    """Make /etc/hosts contain exactly our block for `domains` (none if empty). True if changed."""
    try:
        with open(paths.HOSTS_FILE, encoding="utf-8", errors="replace") as fh:
            current = fh.read()
    except OSError:
        current = "127.0.0.1 localhost\n"
    wanted = strip_hosts_section(current)
    if domains:
        wanted += "\n" + _hosts_section(domains)
    if wanted == current:
        return False
    tmp = paths.HOSTS_FILE + ".focusguard.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(wanted)
        os.chmod(tmp, 0o644)
        os.replace(tmp, paths.HOSTS_FILE)
    except OSError:
        # Some systems bind-mount /etc/hosts; fall back to writing in place.
        with open(paths.HOSTS_FILE, "w", encoding="utf-8") as fh:
            fh.write(wanted)
    return True


CHROMIUM_POLICY = {"DnsOverHttpsMode": "off", "IncognitoModeAvailability": 1}
FIREFOX_KEYS = {
    "DNSOverHTTPS": {"Enabled": False, "Locked": True},
    "DisablePrivateBrowsing": True,
}


def apply_browser_policies(enabled: bool) -> None:
    """Turn off private windows and DNS-over-HTTPS, the two easy ways around the blocker."""
    for d in paths.CHROMIUM_POLICY_DIRS:
        target = os.path.join(d, "focusguard.json")
        try:
            if enabled:
                os.makedirs(d, exist_ok=True)
                _write_if_changed(target, json.dumps(CHROMIUM_POLICY, indent=1) + "\n")
            elif os.path.exists(target):
                os.remove(target)
        except OSError:
            pass
    # Firefox has a single policies.json, so merge into whatever is already there.
    try:
        try:
            with open(paths.FIREFOX_POLICY, encoding="utf-8") as fh:
                doc = json.load(fh)
            if not isinstance(doc, dict):
                return
        except FileNotFoundError:
            if not enabled:
                return
            doc = {}
        except ValueError:
            return  # someone else's file that we cannot parse: leave it alone
        policies = doc.setdefault("policies", {})
        if not isinstance(policies, dict):
            return
        if enabled:
            policies.update(FIREFOX_KEYS)
        else:
            for key, value in FIREFOX_KEYS.items():
                if policies.get(key) == value:
                    del policies[key]
        os.makedirs(os.path.dirname(paths.FIREFOX_POLICY), exist_ok=True)
        _write_if_changed(paths.FIREFOX_POLICY, json.dumps(doc, indent=1) + "\n")
    except OSError:
        pass


def _write_if_changed(path: str, text: str) -> None:
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == text:
                return
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o644)


def _run(cmd) -> int:
    if paths.TEST_MODE:
        return 0
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def set_immutable(flag: bool) -> None:
    """Lock or unlock the program and unit files with the filesystem immutable bit."""
    targets = [p for p in paths.UNIT_FILES if os.path.exists(p)]
    if targets:
        _run(["chattr", "+i" if flag else "-i", *targets])
    if os.path.isdir(paths.INSTALL_DIR):
        _run(["chattr", "-R", "+i" if flag else "-i", paths.INSTALL_DIR])


def ensure_watchdog() -> None:
    """Keep the watchdog timer and our own unit enabled, so a stop or disable does not stick."""
    if _run(["systemctl", "is-active", "--quiet", "focusguard-watchdog.timer"]) != 0:
        _run(["systemctl", "start", "focusguard-watchdog.timer"])
    for unit in ("focusguard-watchdog.timer", "focusguard.service"):
        if _run(["systemctl", "is-enabled", "--quiet", unit]) != 0:
            _run(["systemctl", "enable", unit])
