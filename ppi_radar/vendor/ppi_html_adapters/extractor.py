from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from .config import SourceConfig
from .models import ArticleItem

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
ARTICLE_TYPES = {"Article", "NewsArticle", "Report", "BlogPosting", "PressRelease"}


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def canonicalize_url(base_url: str, value: str) -> str:
    absolute = urljoin(base_url, value.strip())
    parts = urlsplit(absolute)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS])
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def parse_date(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"(\d{4})年(\d{1,2})月(\d{1,2})日", r"\1-\2-\3", text)
    try:
        dt = date_parser.parse(text, fuzzy=True, dayfirst=False)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def fingerprint(source_id: str, url: str, title: str) -> str:
    payload = f"{source_id}\n{url}\n{clean_text(title).casefold()}".encode()
    return hashlib.sha256(payload).hexdigest()


class HtmlExtractor:
    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self._include = tuple(re.compile(p, re.IGNORECASE) for p in config.include_url_patterns)
        self._exclude = tuple(re.compile(p, re.IGNORECASE) for p in config.exclude_url_patterns)

    def extract(self, html: str, base_url: str | None = None) -> list[ArticleItem]:
        base = base_url or self.config.endpoint
        soup = BeautifulSoup(html, "lxml")
        items = self._from_json_ld(soup, base)
        items.extend(self._from_containers(soup, base))
        if len(items) < self.config.min_items:
            items.extend(self._from_links(soup, base))
        return self._deduplicate(items)

    def _url_allowed(self, url: str) -> bool:
        if any(rx.search(url) for rx in self._exclude):
            return False
        return not self._include or any(rx.search(url) for rx in self._include)

    def _make_item(self, title: str, url: str, date: str | None = None, summary: str | None = None) -> ArticleItem | None:
        title = clean_text(title)
        if len(title) < self.config.min_title_length or not self._url_allowed(url):
            return None
        return ArticleItem(
            source_id=self.config.source_id,
            source_name=self.config.source_name,
            title=title,
            url=url,
            published_at=parse_date(date),
            summary=clean_text(summary)[:1000] or None,
            language=self.config.language,
            fingerprint=fingerprint(self.config.source_id, url, title),
        )

    def _from_json_ld(self, soup: BeautifulSoup, base: str) -> list[ArticleItem]:
        output: list[ArticleItem] = []
        for script in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            for obj in self._walk_json(data):
                kind = obj.get("@type")
                kinds = set(kind if isinstance(kind, list) else [kind])
                if not kinds.intersection(ARTICLE_TYPES):
                    continue
                title = obj.get("headline") or obj.get("name")
                raw_url = obj.get("url") or obj.get("mainEntityOfPage")
                if isinstance(raw_url, dict):
                    raw_url = raw_url.get("@id") or raw_url.get("url")
                if not title or not raw_url:
                    continue
                item = self._make_item(
                    str(title), canonicalize_url(base, str(raw_url)),
                    str(obj.get("datePublished") or ""), str(obj.get("description") or ""),
                )
                if item:
                    output.append(item)
        return output

    def _walk_json(self, value: Any) -> Iterable[dict[str, Any]]:
        if isinstance(value, dict):
            yield value
            for nested in value.values():
                yield from self._walk_json(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from self._walk_json(nested)

    @staticmethod
    def _first(node: Tag, selectors: tuple[str, ...]) -> Tag | None:
        for selector in selectors:
            match = node.select_one(selector)
            if match:
                return match
        return None

    def _from_containers(self, soup: BeautifulSoup, base: str) -> list[ArticleItem]:
        best: list[ArticleItem] = []
        for selector in self.config.item_selectors:
            output: list[ArticleItem] = []
            for node in (x for x in soup.select(selector) if isinstance(x, Tag)):
                title_node = self._first(node, self.config.title_selectors)
                title_link = None
                if title_node:
                    title_link = title_node if title_node.name == "a" else title_node.select_one("a[href]")
                link = title_link or self._first(node, self.config.link_selectors)
                if link is None or not link.get("href"):
                    continue
                title = clean_text(title_node.get_text(" ") if title_node else link.get_text(" "))
                date_node = self._first(node, self.config.date_selectors)
                summary_node = self._first(node, self.config.summary_selectors)
                date = date_node.get("datetime") if date_node else None
                date = str(date or (date_node.get_text(" ") if date_node else ""))
                item = self._make_item(
                    title,
                    canonicalize_url(base, str(link.get("href"))),
                    date,
                    summary_node.get_text(" ") if summary_node else None,
                )
                if item:
                    output.append(item)
                if len(output) >= 300:
                    break
            if len(output) > len(best):
                best = output
        return best

    def _from_links(self, soup: BeautifulSoup, base: str) -> list[ArticleItem]:
        output: list[ArticleItem] = []
        for link in soup.select("main a[href], article a[href], #content a[href], .content a[href]")[:600]:
            href = link.get("href")
            if not href:
                continue
            title = clean_text(link.get_text(" ") or link.get("title"))
            item = self._make_item(title, canonicalize_url(base, str(href)))
            if item:
                output.append(item)
        return output

    @staticmethod
    def _deduplicate(items: list[ArticleItem]) -> list[ArticleItem]:
        seen: set[str] = set()
        output: list[ArticleItem] = []
        for item in items:
            key = item.url.rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            output.append(item)
        output.sort(key=lambda x: (x.published_at or "", x.title), reverse=True)
        return output
