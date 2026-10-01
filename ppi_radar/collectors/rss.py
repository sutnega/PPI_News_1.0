"""
Сбор новостей по RSS из рабочих источников базы (fetch_method == RSS).

Было: extract_rss_urls.py + collect_rss.py, с захардкоженными путями
/home/user/workspace/... (песочница Perplexity). Здесь — единая функция,
путь к базе и файлу вывода настраиваются через ppi_radar.config.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import urllib3

from ..config import DATA_DIR, RSS_WINDOW_HOURS, UA
from ..error_log import log_error
from ..sources import extract_rss_sources

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

RAW_OUTPUT = DATA_DIR / "rss_collected_raw.json"


def collect_rss(window_hours: int = RSS_WINDOW_HOURS, sources: list[dict] | None = None) -> dict:
    sources = sources if sources is not None else extract_rss_sources()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)

    results: list[dict] = []
    errors: list[dict] = []
    per_source: list[dict] = []  # диагностика: сколько реально отдал каждый источник

    for src in sources:
        sid = src["source_id"]
        url = src["rss_url"]
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=15, verify=False)
            if resp.status_code != 200:
                errors.append({"source_id": sid, "url": url, "error": f"HTTP {resp.status_code}"})
                log_error("rss", "http_error", f"HTTP {resp.status_code}", source_id=sid, url=url)
                per_source.append({"source_id": sid, "country": src["country"], "org": src["org"],
                                    "total_entries": 0, "in_window_entries": 0,
                                    "status": f"HTTP {resp.status_code}"})
                continue
            feed = feedparser.parse(resp.content)
            if feed.bozo and not feed.entries:
                errors.append({"source_id": sid, "url": url, "error": f"parse error: {feed.bozo_exception}"})
                log_error("rss", "parse_error", str(feed.bozo_exception), source_id=sid, url=url)
                per_source.append({"source_id": sid, "country": src["country"], "org": src["org"],
                                    "total_entries": 0, "in_window_entries": 0,
                                    "status": f"ошибка парсинга: {feed.bozo_exception}"})
                continue

            count_recent = 0
            for entry in feed.entries[:30]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = (entry.get("summary") or entry.get("description") or "").strip()
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc) if published else None
                in_window = pub_dt is not None and pub_dt >= cutoff
                if in_window:
                    count_recent += 1
                results.append({
                    "source_id": sid,
                    "country": src["country"],
                    "source_type": src["source_type"],
                    "org": src["org"],
                    "title": title,
                    "link": link,
                    "summary": summary[:500],
                    "published": pub_dt.isoformat() if pub_dt else None,
                    "in_window": in_window,
                })
            status = "OK" if count_recent > 0 else ("нет новых за окно" if feed.entries else "пустой фид")
            per_source.append({"source_id": sid, "country": src["country"], "org": src["org"],
                                "total_entries": len(feed.entries), "in_window_entries": count_recent,
                                "status": status})
            print(f"OK {sid} ({src['country']}): {len(feed.entries)} записей всего, {count_recent} за {window_hours}ч")
        except Exception as e:
            errors.append({"source_id": sid, "url": url, "error": str(e)})
            log_error("rss", "fetch_error", str(e), source_id=sid, url=url)
            per_source.append({"source_id": sid, "country": src["country"], "org": src["org"],
                                "total_entries": 0, "in_window_entries": 0, "status": f"ошибка: {e}"})
            print(f"ERROR {sid} ({src['country']}): {e}")

    payload = {
        "collected_at": now.isoformat(),
        "window_hours": window_hours,
        "items": results,
        "errors": errors,
        "per_source": per_source,
    }
    RAW_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    from ..archive import append_to_archive
    new_archived = append_to_archive(results)

    print(f"\nВсего собрано: {len(results)} записей, ошибок: {len(errors)}")
    print(f"Новых в архиве: {new_archived} (архив накопительный, старое не теряется)")
    for e in errors:
        print(" -", e["source_id"], e["error"])
    return payload


if __name__ == "__main__":
    collect_rss()
