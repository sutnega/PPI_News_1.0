from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Self

import httpx

from .config import SourceConfig
from .errors import ExtractionError
from .extractor import HtmlExtractor
from .fetcher import HttpFetcher
from .models import ArticleItem, RunReport


class ConfiguredHTMLAdapter:
    CONFIG: SourceConfig

    def __init__(
        self,
        *,
        respect_robots: bool = True,
        retries: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        self.fetcher = HttpFetcher(self.CONFIG, respect_robots=respect_robots, retries=retries, client=client)
        self.extractor = HtmlExtractor(self.CONFIG)

    def close(self) -> None:
        self.fetcher.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def collect(self, *, limit: int = 50) -> tuple[list[ArticleItem], RunReport]:
        started = time.monotonic()
        warnings: list[str] = []
        response = self.fetcher.fetch()
        items = self.extractor.extract(response.text, response.url)
        if not items:
            raise ExtractionError(f"No valid items extracted from {self.CONFIG.endpoint}")
        if len(items) < self.CONFIG.min_items:
            warnings.append(f"Only {len(items)} item(s) extracted; expected at least {self.CONFIG.min_items}")
        emitted = items[: max(1, limit)]
        report = RunReport(
            source_id=self.CONFIG.source_id,
            source_name=self.CONFIG.source_name,
            endpoint=response.url,
            status="OK" if not warnings else "DEGRADED",
            fetched_items=len(items),
            emitted_items=len(emitted),
            elapsed_seconds=round(time.monotonic() - started, 3),
            warnings=warnings,
        )
        return emitted, report

    def extract_html(self, html: str, *, base_url: str | None = None, limit: int = 50) -> list[ArticleItem]:
        return self.extractor.extract(html, base_url)[: max(1, limit)]

    @staticmethod
    def jsonl(items: Iterable[ArticleItem]) -> str:
        import json
        return "\n".join(json.dumps(item.to_dict(), ensure_ascii=False) for item in items)
