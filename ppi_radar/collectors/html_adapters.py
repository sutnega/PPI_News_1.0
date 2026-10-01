"""
Обёртка над пакетом адаптеров — 21 HTML-адаптер для источников, у которых
не нашлось пригодного RSS/API. Среди них 3 по Китаю уровня A/B (Caixin
Global, China Paper Magazine Network / cppmp, APP China) — их подключение
даёт заметно больше для покрытия Китая, чем починка одного скрипта под
конкретный сайт.

Пакет вендорится прямо внутрь проекта (ppi_radar/vendor/ppi_html_adapters/)
— по явному решению: не держать отдельную ручную установку через pip,
чтобы всё работало сразу после распаковки проекта, без дополнительных
шагов. См. ppi_radar/vendor/README.md — как обновить исходники, если
придёт новая версия пакета.

probe-all надо гонять именно с той машины/сервера, где реально крутится
Radar: доступность части источников зависит от IP/WAF/геолокации.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..config import DATA_DIR, RSS_WINDOW_HOURS
from ..country_map import normalize_country
from ..error_log import log_error
from ..source_priority import get_priority
from ..vendor.ppi_html_adapters.registry import MODULES, get_adapter_class

OUTPUT_PATH = DATA_DIR / "html_adapters_collected_raw.json"


def _adapter_slugs() -> list[str]:
    return list(MODULES.keys())


def is_available() -> bool:
    """
    Пакет вендорен внутрь проекта, поэтому всегда доступен — функция
    оставлена для обратной совместимости с местами в UI/CLI, которые её
    вызывают (раньше проверяла внешнюю установку).
    """
    return True


def _normalize(article, config, in_window_cutoff) -> dict:
    pub_dt = None
    if article.published_at:
        try:
            pub_dt = datetime.fromisoformat(article.published_at.replace("Z", "+00:00"))
        except ValueError:
            pub_dt = None
    return {
        "source_id": config.source_id,
        "country": normalize_country(config.country),
        "source_type": "html_adapter",
        "org": config.source_name,
        "channel_priority": get_priority(config.endpoint),
        "title": article.title,
        "link": article.url,
        "summary": (article.summary or "")[:500],
        "published": pub_dt.isoformat() if pub_dt else None,
        # Как и в headless_news.py: даты на HTML-страницах часто ненадёжны
        # (относительные форматы, отсутствие точной даты) — если распознать
        # не удалось, по умолчанию считаем "в окне", фактическую проверку
        # свежести берёт на себя LLM на этапе редактуры.
        "in_window": True if pub_dt is None else pub_dt >= in_window_cutoff,
    }


def collect_html_adapters(limit_per_source: int = 20, skip: set[str] | None = None
                           ) -> tuple[list[dict], list[dict]]:
    """
    Возвращает (items, per_source_stats) — та же форма, что у
    collectors.rss.collect_rss()/headless_news.collect_headless_with_stats(),
    чтобы app.py мог показывать одинаковую диагностику для всех коллекторов.
    """
    skip = skip or set()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=RSS_WINDOW_HOURS)

    all_items: list[dict] = []
    per_source: list[dict] = []

    for slug in _adapter_slugs():
        if slug in skip:
            continue
        print(f"html-адаптер: {slug} ...")
        try:
            adapter_cls = get_adapter_class(slug)
            with adapter_cls() as adapter:
                articles, report = adapter.collect(limit=limit_per_source)
            items = [_normalize(a, adapter.CONFIG, cutoff) for a in articles]
            status = report.status
            if report.warnings:
                status += f" ({'; '.join(report.warnings)})"
        except Exception as e:
            items = []
            status = f"ошибка: {e}"
            print(f"  ERROR {slug}: {e}")
            log_error("html_adapters", "adapter_error", str(e), slug=slug)

        print(f"  -> {len(items)} записей")
        all_items.extend(items)
        country = items[0]["country"] if items else "?"
        per_source.append({"source_id": slug, "country": country, "org": slug,
                            "total_entries": len(items), "in_window_entries": len(items), "status": status})

    OUTPUT_PATH.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")

    from ..archive import append_to_archive
    new_archived = append_to_archive(all_items)
    print(f"Новых в архиве: {new_archived}")

    return all_items, per_source


if __name__ == "__main__":
    collect_html_adapters()
