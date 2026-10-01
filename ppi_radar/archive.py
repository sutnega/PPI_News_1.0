"""
Архив всех когда-либо собранных новостей.

Проблема, которую это решает: data/rss_collected_raw.json и
data/headless_collected_raw.json перезаписываются на каждом прогоне сбора —
если сегодня собрали 200 новостей, а завтра снова 200 (частично другие),
вчерашние бесследно исчезают. Здесь — накопительный архив: каждая новая
запись (по ссылке — уникальный ключ) добавляется один раз и остаётся
навсегда, независимо от того, что происходит в data/*.json дальше по
пайплайну.

Формат хранения — JSON Lines (по записи на строку): дописывать в конец
файла дёшево и не требует перечитывать и переписывать весь файл целиком
при каждом добавлении, в отличие от одного большого JSON-массива.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import DATA_DIR

ARCHIVE_DIR = DATA_DIR / "archive"
ARCHIVE_PATH = ARCHIVE_DIR / "news_archive.jsonl"

ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def _existing_links() -> set[str]:
    if not ARCHIVE_PATH.exists():
        return set()
    links = set()
    with open(ARCHIVE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                links.add(json.loads(line).get("link"))
            except json.JSONDecodeError:
                continue
    return links


def append_to_archive(items: list[dict]) -> int:
    """Дописывает в архив только те записи, которых там ещё нет (по ссылке). Возвращает число новых."""
    existing = _existing_links()
    now = datetime.now(timezone.utc).isoformat()
    new_count = 0
    with open(ARCHIVE_PATH, "a", encoding="utf-8") as f:
        for it in items:
            link = it.get("link")
            if not link or link in existing:
                continue
            record = dict(it)
            record["archived_at"] = now
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            existing.add(link)
            new_count += 1
    return new_count


def load_archive(limit: int | None = None, country: str | None = None) -> list[dict]:
    """Читает архив (по умолчанию весь). limit — только последние N записей."""
    if not ARCHIVE_PATH.exists():
        return []
    records = []
    with open(ARCHIVE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if country and rec.get("country") != country:
                continue
            records.append(rec)
    if limit:
        records = records[-limit:]
    return records


def archive_stats() -> dict:
    records = load_archive()
    from collections import Counter
    by_country = Counter(r.get("country", "?") for r in records)
    return {
        "total": len(records),
        "by_country": dict(sorted(by_country.items(), key=lambda x: -x[1])),
        "oldest": min((r.get("archived_at", "") for r in records), default=None),
        "newest": max((r.get("archived_at", "") for r in records), default=None),
    }
