"""focusguardctl - command line control for FocusGuard."""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime

from . import client, link


def _fmt(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%a %H:%M") if ts else "-"


def _password(status: dict) -> str | None:
    return getpass.getpass("FocusGuard password: ") if status.get("has_password") else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="focusguardctl", description="Control the FocusGuard blocker.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show whether blocking is on")
    p = sub.add_parser("start", help="start a focus session now")
    p.add_argument("minutes", type=int)
    sub.add_parser("stop", help="end a manual focus session early")
    sub.add_parser("set-password", help="set, change or remove the password")
    sub.add_parser("prepare-uninstall", help="used by uninstall.sh")
    sub.add_parser("link", help="link a phone: create and show a link code")
    sub.add_parser("unlink", help="remove the phone link")
    args = parser.parse_args(argv)

    try:
        status = client.call("status")["status"]
        if args.command == "status":
            if status["active"]:
                print(f"Blocking is ON until {_fmt(status['until'])} ({status['reason']}).")
            else:
                print(f"Blocking is off. Next scheduled block: {_fmt(status['next_start'])}.")
            print(f"Strict mode: {'on' if status['strict'] else 'off'}. "
                  f"Password: {'set' if status['has_password'] else 'not set'}.")
            for browser, age in status["extensions"].items():
                print(f"Extension active in {browser} (seen {age}s ago).")
            phone = status.get("phone_link", {})
            if phone.get("linked"):
                print("Phone link: " + (f"error: {phone['last_error']}" if phone.get("last_error") else
                                        f"last sent {_fmt(phone['last_ok'])}" if phone.get("last_ok") else "waiting to send"))
            return 0
        if args.command == "start":
            resp = client.call("start_session", minutes=args.minutes)
        elif args.command == "stop":
            resp = client.call("stop_session", password=_password(status))
        elif args.command == "link":
            existing = client.call("get_config")["config"].get("link")
            if existing:
                print("Already linked. Code for the phone app: " + link.format_code(existing["code"]))
                return 0
            resp = client.call("link_create", password=_password(status))
            if resp.get("ok"):
                print("Enter this code in the phone app: " + link.format_code(resp["code"]))
                return 0
        elif args.command == "unlink":
            resp = client.call("link_remove", password=_password(status))
        elif args.command == "prepare-uninstall":
            resp = client.call("prepare_uninstall", password=_password(status))
        else:
            old = _password(status)
            new = getpass.getpass("New password (empty to remove): ")
            if new != getpass.getpass("Repeat new password: "):
                print("The passwords do not match.", file=sys.stderr)
                return 1
            resp = client.call("set_password", password=old, new_password=new or None)
    except client.ServiceError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not resp.get("ok"):
        print(client.error_text(resp), file=sys.stderr)
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
