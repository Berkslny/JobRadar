"""Access control for the panel and the JSON API.

* No JOBRADAR_API_TOKEN: only direct requests from this machine are served
  (the Mac setup). Anything that came through a proxy or tunnel is refused.
* With a token: the API needs `Authorization: Bearer <token>`, the HTML panel
  needs a session cookie obtained by logging in with the same token."""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time

from fastapi import Request

from jobradar.config import AppConfig

COOKIE = "jr_session"
PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-real-ip", "forwarded")
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def api_token(cfg: AppConfig) -> str:
    return os.environ.get(cfg.server.api_token_env, "").strip()


def _sign(token: str, exp: int) -> str:
    return hmac.new(token.encode(), f"jobradar-session:{exp}".encode(), hashlib.sha256).hexdigest()


def make_session(token: str, days: int) -> str:
    exp = int(time.time()) + days * 86400
    return f"{exp}.{_sign(token, exp)}"


def valid_session(token: str, value: str | None) -> bool:
    if not token or not value or "." not in value:
        return False
    exp_s, sig = value.split(".", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    return exp > time.time() and hmac.compare_digest(sig, _sign(token, exp))


def bearer_ok(token: str, header: str | None) -> bool:
    if not token or not header or not header.lower().startswith("bearer "):
        return False
    return hmac.compare_digest(header[7:].strip().encode(), token.encode())


def is_direct_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in LOCAL_HOSTS and not any(h in request.headers for h in PROXY_HEADERS)


def client_ip(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "?"))


def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https" \
        or "cf-visitor" in request.headers and "https" in request.headers.get("cf-visitor", "")


class LoginLimiter:
    """At most `limit` failed logins per client in `window` seconds."""

    def __init__(self, limit: int = 8, window: int = 900):
        self.limit, self.window = limit, window
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            recent = [t for t in self._fails.get(key, []) if now - t < self.window]
            self._fails[key] = recent
            return len(recent) >= self.limit

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails.setdefault(key, []).append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
