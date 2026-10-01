"""
Расширение охвата: автопоиск рабочих RSS-фидов среди непроверенных
источников базы (endpoint_status == DISCOVERY_REQUIRED).

Не гадает адрес фида вслепую (не перебирает /feed, /rss.xml и т.п.) — вместо
этого использует тот же механизм, что и любой RSS-ридер: ищет в HTML
главной страницы <link rel="alternate" type="application/rss+xml"|"application/atom+xml">
и проверяет найденный адрес реальным парсингом (feedparser). Источник
считается кандидатом, только если фид реально парсится и содержит записи —
никаких "предположительно рабочих".

Найденные рабочие фиды сохраняются ОТДЕЛЬНО от официальной базы v9
(в sources/discovered_rss.json), не трогая исходный CSV. sources.py
подмешивает их к рабочим RSS-источникам автоматически.
"""
from __future__ import annotations

import json

import feedparser
import requests
from bs4 import BeautifulSoup

from ..config import SOURCES_DIR, UA
from ..country_map import normalize_country
from ..sources import load_sources

DISCOVERED_PATH = SOURCES_DIR / "discovered_rss.json"

FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/x-atom+xml")


def _find_feed_link(page_url: str, timeout: int = 15) -> str | None:
    try:
        resp = requests.get(page_url, headers={"User-Agent": UA}, timeout=timeout, verify=False)
        resp.raise_for_status()
    except Exception:
        return None
    soup = BeautifulSoup(resp.text, "lxml")
    link = soup.find("link", attrs={"rel": "alternate", "type": FEED_TYPES})
    if not link or not link.get("href"):
        return None
    href = link["href"]
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        from urllib.parse import urljoin
        href = urljoin(page_url, href)
    return href


def _validate_feed(feed_url: str, timeout: int = 15) -> dict | None:
    try:
        resp = requests.get(feed_url, headers={"User-Agent": UA}, timeout=timeout, verify=False)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception:
        return None
    if not feed.entries:
        return None
    return {"feed_title": feed.feed.get("title", ""), "entry_count": len(feed.entries)}


def probe_source(row: dict) -> dict | None:
    """Пробует найти и провалидировать RSS-фид для одной строки базы источников."""
    page_url = row.get("list_url", "").strip()
    if not page_url or not page_url.startswith("http"):
        return None
    feed_url = _find_feed_link(page_url)
    if not feed_url:
        return None
    validation = _validate_feed(feed_url)
    if not validation:
        return None
    return {
        "source_id": row["source_id"],
        "country": normalize_country(row.get("country", "")),
        "source_type": row.get("source_type", ""),
        "org": row.get("organization", ""),
        "rss_url": feed_url,
        "priority": row.get("editorial_priority", ""),
        "discovered_from": page_url,
        **validation,
    }


def discover_candidates(rows: list[dict] | None = None, progress_callback=None) -> list[dict]:
    """
    Проверяет все непроверенные источники, у которых fetch_method упоминает
    RSS (сейчас это 47 из 245), и возвращает те, для которых реально
    нашёлся и провалидировался рабочий фид.
    """
    rows = rows if rows is not None else load_sources()
    candidates = [
        r for r in rows
        if r.get("endpoint_status", "").strip() == "DISCOVERY_REQUIRED"
        and "RSS" in r.get("fetch_method", "")
    ]

    found = []
    for i, row in enumerate(candidates):
        if progress_callback:
            progress_callback(i, len(candidates), row)
        result = probe_source(row)
        if result:
            found.append(result)
            print(f"  ✓ {row['source_id']} ({row.get('country')}): найден рабочий фид, "
                  f"{result['entry_count']} записей")
        else:
            print(f"  ✗ {row['source_id']} ({row.get('country')}): фид не найден/не парсится")
    return found


def load_discovered() -> list[dict]:
    if not DISCOVERED_PATH.exists():
        return []
    return json.loads(DISCOVERED_PATH.read_text(encoding="utf-8"))


def save_discovered(candidates: list[dict], merge: bool = True) -> None:
    """Сохраняет найденные источники в sources/discovered_rss.json (не трогая официальный CSV)."""
    existing = load_discovered() if merge else []
    by_id = {c["source_id"]: c for c in existing}
    for c in candidates:
        by_id[c["source_id"]] = c
    DISCOVERED_PATH.write_text(
        json.dumps(list(by_id.values()), ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    found = discover_candidates()
    print(f"\nНайдено рабочих фидов: {len(found)}")
    if found:
        save_discovered(found)
        print(f"Сохранено в {DISCOVERED_PATH}")
