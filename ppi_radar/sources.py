"""
Загрузка и фильтрация базы источников (PPI_Country_Industry_Radar_recon_v9.csv).
"""
from __future__ import annotations

import csv
import re
from typing import Any
from urllib.parse import urlparse

from .config import SOURCES_CSV
from .country_map import normalize_country

WORKING_STATUSES = {"READY_FOR_TECH_TEST", "VALIDATED_WORKING"}

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

# Источники, помеченные в CSV как fetch_method=RSS, но по факту НЕ
# являющиеся рабочим RSS-фидом (проверено на практике — feedparser падает
# с "not well-formed", потому что это HTML-страница, а не XML). Такие
# перенесены в собственный HTML-парсер (см. collectors/headless_news.py) —
# здесь их нужно исключить, чтобы не тратить запрос и не засорять лог
# ошибками, которые всё равно ничего не дадут.
#   SRC-0370 (China National Pulp and Paper Research Institute, cnppri.com) —
#   заметка самой разведки: "страница доступна без JS, но общий эвристический
#   алгоритм цепляет пункты меню/навигации, не новости — нужен точный
#   CSS-селектор" — см. parse_cnppri_china() в headless_news.py.
KNOWN_BROKEN_RSS_SOURCE_IDS = {"SRC-0370"}


def load_sources(csv_path=None) -> list[dict[str, Any]]:
    csv_path = csv_path or SOURCES_CSV
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def working_sources(rows: list[dict] | None = None) -> list[dict]:
    """Источники, технически проверенные и рабочие (54 из 306 на v9)."""
    rows = rows if rows is not None else load_sources()
    return [r for r in rows if r.get("endpoint_status", "").strip() in WORKING_STATUSES]


def by_source_id(rows: list[dict] | None = None) -> dict[str, dict]:
    rows = rows if rows is not None else load_sources()
    return {r["source_id"]: r for r in rows if r.get("source_id")}


def extract_rss_sources(rows: list[dict] | None = None, include_discovered: bool = True) -> list[dict]:
    """
    Рабочие источники с fetch_method == RSS, с извлечённым фактическим
    RSS URL из поля list_url (там может быть markdown-ссылка вида
    "[RSS](https://...)" либо голый URL).

    Если include_discovered=True (по умолчанию), дополнительно подмешивает
    источники, найденные автопоиском среди DISCOVERY_REQUIRED
    (см. collectors/discover_rss.py, sources/discovered_rss.json) —
    это способ расширять охват без ручной разведки каждого источника.

    Дедуп по домену: в официальной базе встречаются источники, указывающие
    на один и тот же фид под разными source_id (например SRC-0311 "The
    Paper Story" и SRC-0375 "PAMSA" оба ведут на thepaperstory.co.za/feed/)
    — такой фид не должен опрашиваться дважды. Оставляем первое вхождение.

    Каждому источнику проставляется channel_priority (A/B/C/NO/UNRANKED) —
    см. source_priority.py — для каскадного отбора A→B→C в editor.py.
    """
    from .source_priority import get_priority

    rows = working_sources(rows)
    rss_rows = [r for r in rows
                if r.get("fetch_method", "").strip() == "RSS"
                and r.get("source_id") not in KNOWN_BROKEN_RSS_SOURCE_IDS]

    result = []
    seen_domains: set[str] = set()
    for r in rss_rows:
        list_url_field = r.get("list_url", "")
        links = _MD_LINK_RE.findall(list_url_field)
        rss_url = None
        if links:
            for label, url in links:
                if "rss" in label.lower() or "feed" in label.lower():
                    rss_url = url
                    break
            if not rss_url:
                rss_url = links[0][1]
        else:
            rss_url = list_url_field.strip()

        if not rss_url:
            continue

        domain = urlparse(rss_url).netloc.replace("www.", "")
        if domain in seen_domains:
            continue
        seen_domains.add(domain)

        result.append({
            "source_id": r["source_id"],
            "country": normalize_country(r.get("country", "")),
            "source_type": r.get("source_type", ""),
            "org": r.get("organization", ""),
            "rss_url": rss_url,
            "priority": r.get("editorial_priority", ""),
            "channel_priority": get_priority(rss_url),
        })

    if include_discovered:
        from .collectors.discover_rss import load_discovered
        existing_ids = {r["source_id"] for r in result}
        for d in load_discovered():
            domain = urlparse(d["rss_url"]).netloc.replace("www.", "")
            if d["source_id"] in existing_ids or domain in seen_domains:
                continue
            seen_domains.add(domain)
            entry = {k: d[k] for k in ("source_id", "country", "source_type", "org", "rss_url", "priority")}
            entry["channel_priority"] = get_priority(d["rss_url"])
            result.append(entry)

    return result


def coverage_summary(rows: list[dict] | None = None) -> dict:
    """Быстрая сводка охвата базы — то же, что в README/Knowledge Base."""
    rows = rows if rows is not None else load_sources()
    total = len(rows)
    ready = sum(1 for r in rows if r.get("endpoint_status", "").strip() in WORKING_STATUSES)
    discovery = sum(1 for r in rows if r.get("endpoint_status", "").strip() == "DISCOVERY_REQUIRED")
    dead = total - ready - discovery
    return {"total": total, "working": ready, "discovery_required": discovery, "blocked_or_dead": dead}
