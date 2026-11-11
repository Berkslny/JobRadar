"""HTTP helpers with polite retries."""

from __future__ import annotations

import time
from typing import Any

import httpx

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Tests set this to a no-op so retries do not slow them down.
sleep = time.sleep


class HTTPStatusError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}" + (f": {body[:200]}" if body else ""))
        self.status = status
        self.url = url


def make_client(timeout: float = 25.0, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
        transport=transport,
    )


def request(
    client: httpx.Client, method: str, url: str, *, retries: int = 3, backoff: float = 1.5, **kwargs: Any
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise
            sleep(backoff * (2 ** attempt))
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            retry_after = resp.headers.get("Retry-After", "")
            try:
                wait = float(retry_after)
            except ValueError:
                wait = backoff * (2 ** attempt)
            sleep(min(wait, 30.0))
            continue
        return resp
    if last_exc:  # pragma: no cover - loop always returns or raises
        raise last_exc
    raise RuntimeError("unreachable")


def get_json(client: httpx.Client, url: str, **kwargs: Any) -> Any:
    resp = request(client, "GET", url, **kwargs)
    if resp.status_code >= 400:
        raise HTTPStatusError(resp.status_code, str(resp.request.url), resp.text)
    return resp.json()


def post_json(client: httpx.Client, url: str, payload: Any, **kwargs: Any) -> Any:
    resp = request(client, "POST", url, json=payload, **kwargs)
    if resp.status_code >= 400:
        raise HTTPStatusError(resp.status_code, str(resp.request.url), resp.text)
    return resp.json()


def get_text(client: httpx.Client, url: str, **kwargs: Any) -> str:
    resp = request(client, "GET", url, **kwargs)
    if resp.status_code >= 400:
        raise HTTPStatusError(resp.status_code, str(resp.request.url))
    return resp.text
