from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class ArticleItem:
    source_id: str
    source_name: str
    title: str
    url: str
    published_at: str | None = None
    summary: str | None = None
    language: str | None = None
    fingerprint: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunReport:
    source_id: str
    source_name: str
    endpoint: str
    status: str
    fetched_items: int
    emitted_items: int
    elapsed_seconds: float
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

