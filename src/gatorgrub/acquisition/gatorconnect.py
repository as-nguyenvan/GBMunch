from __future__ import annotations

import json
import ssl
import time
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlencode

SEARCH_URL = "https://gatorconnect.ufl.edu/api/discovery/event/search"
USER_AGENT = "GatorGrub/0.1 (+UF promptathon research; polite public discovery client)"
DEFAULT_PAGE_SIZE = 10


def _default_ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context


def http_get_json(url: str, timeout: int = 45) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, context=_default_ssl_context(), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class GatorConnectClient:
    """Public GatorConnect event listing client. Does not create FoodEvent objects."""

    def __init__(self, getter: Callable[[str], dict[str, Any]] | None = None,
                 page_size: int = DEFAULT_PAGE_SIZE, delay_s: float = 0.2):
        self._get = getter or http_get_json
        self.page_size = page_size
        self.delay_s = delay_s

    def search_url(self, skip: int) -> str:
        return f"{SEARCH_URL}?{urlencode({'top': self.page_size, 'skip': skip})}"

    def iter_events(self, *, limit: int | None = None) -> Iterator[dict[str, Any]]:
        skip = 0
        yielded = 0
        total = None
        while True:
            payload = self._get(self.search_url(skip))
            if total is None:
                total = payload.get("@odata.count")
            batch = list(payload.get("value") or [])
            if not batch:
                break
            for event in batch:
                yield event
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            skip += len(batch)
            if total is not None and skip >= total:
                break
            if len(batch) < self.page_size:
                break
            if self.delay_s:
                time.sleep(self.delay_s)
