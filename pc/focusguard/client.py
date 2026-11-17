"""Talk to the FocusGuard service over its control socket."""
from __future__ import annotations

import json
import socket

from . import paths


class ServiceError(Exception):
    pass


def call(cmd: str, timeout: float = 15, **params) -> dict:
    req = dict(params, cmd=cmd)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(paths.SOCKET)
            s.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ServiceError(f"The FocusGuard service is not reachable ({exc}).") from exc


def error_text(resp: dict) -> str:
    return resp.get("message") or resp.get("error") or "Unknown error."
