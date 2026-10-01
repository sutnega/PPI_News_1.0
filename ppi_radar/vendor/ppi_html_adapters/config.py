from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceConfig:
    slug: str
    source_id: str
    source_name: str
    endpoint: str
    country: str
    language: str
    item_selectors: tuple[str, ...] = ("article", ".news-item", ".card", "li")
    title_selectors: tuple[str, ...] = ("h2", "h3", ".title", "[class*='title']")
    link_selectors: tuple[str, ...] = ("a[href]",)
    date_selectors: tuple[str, ...] = ("time", "[datetime]", ".date", "[class*='date']")
    summary_selectors: tuple[str, ...] = ("p", ".summary", ".excerpt", "[class*='description']")
    include_url_patterns: tuple[str, ...] = ()
    exclude_url_patterns: tuple[str, ...] = (
        r"/about/?$", r"/contact/?$", r"/privacy", r"/terms", r"/login", r"/search",
        r"javascript:", r"mailto:", r"tel:", r"\.jpg$", r"\.png$", r"\.svg$",
    )
    min_items: int = 1
    min_title_length: int = 8
    rate_limit_seconds: float = 2.0
    timeout_seconds: float = 25.0
    requires_metadata_only: bool = False
    notes: str = ""

