from __future__ import annotations

import logging
import random
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Self
from urllib.parse import urljoin, urlsplit

import httpx

from .config import SourceConfig
from .errors import FetchError, RobotsDenied

LOGGER = logging.getLogger(__name__)
USER_AGENT = "PPI-Radar/1.0 (+technical news monitoring; contact: configure-in-deployment)"


@dataclass(slots=True)
class FetchResponse:
    url: str
    text: str
    status_code: int
    content_type: str


class HttpFetcher:
    def __init__(
        self,
        config: SourceConfig,
        *,
        respect_robots: bool = True,
        retries: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.respect_robots = respect_robots
        self.retries = retries
        self.client = client or httpx.Client(
            follow_redirects=True,
            trust_env=False,
            timeout=config.timeout_seconds,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                "Accept-Language": "en,ru;q=0.8,*;q=0.5",
            },
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _robots_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        robots_url = urljoin(f"{parts.scheme}://{parts.netloc}", "/robots.txt")
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self.client.get(robots_url)
            if response.status_code >= 400:
                LOGGER.warning("robots.txt unavailable (%s); treating as unknown", response.status_code)
                return True
            parser.parse(response.text.splitlines())
            return parser.can_fetch(USER_AGENT, url)
        except httpx.HTTPError as exc:
            LOGGER.warning("robots.txt check failed: %s; treating as unknown", exc)
            return True

    def fetch(self, url: str | None = None) -> FetchResponse:
        target = url or self.config.endpoint
        if self.respect_robots and not self._robots_allowed(target):
            raise RobotsDenied(f"robots.txt denies {target}")

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            if attempt > 1:
                delay = self.config.rate_limit_seconds * (2 ** (attempt - 2)) + random.uniform(0, 0.4)
                time.sleep(delay)
            try:
                response = self.client.get(target)
                if response.status_code in {403, 429}:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        time.sleep(min(int(retry_after), 60))
                    raise FetchError(f"HTTP {response.status_code} for {target}")
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type.lower() and "xhtml" not in content_type.lower():
                    raise FetchError(f"Unexpected content type {content_type!r} for {target}")
                return FetchResponse(str(response.url), response.text, response.status_code, content_type)
            except (httpx.HTTPError, FetchError) as exc:
                last_error = exc
                LOGGER.warning("fetch attempt %s/%s failed: %s", attempt, self.retries, exc)
        raise FetchError(str(last_error) if last_error else f"Could not fetch {target}")
