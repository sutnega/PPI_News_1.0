"""
Приоритет источника для каскадного отбора A → B → C (см.
TZ_PPI_Radar_AI_pipeline_for_Misha.docx, раздел 8 "Корзины и точная
логика A → B → C").

Смысл: не все источники равноценны для редакционного отбора. A — опорное
ядро (лучшие/обязательные по рынку), B — сильный второй эшелон, C —
берётся только если в A и B по этой позиции ничего не нашлось, NO —
источник продолжает собираться в общую базу, но никогда не участвует
в конкурсе за место в дневном дайджесте.

Правило каскада строгое: если в A есть подходящий кандидат — B и C НЕ
участвуют вообще, даже если там формально более "интересная" новость.
Уровни запрещено смешивать в рамках одной позиции (см. editor.py).

Соответствие "домен → приоритет" взято из финального ранжирования
(PPI_Radar_first_channel_FINAL_for_Misha.xlsx, лист 36_First_Channel_Final)
и сохранено в sources/first_channel_priority.csv — отдельно от основной
базы v9, чтобы не переписывать её вручную построчно.

Источники, для которых приоритет не найден (ещё не ранжированы), получают
уровень UNRANKED и участвуют в каскаде ПОСЛЕ C — то есть не исчезают молча
из дайджеста, а становятся кандидатом последней очереди. Так подключение
новых источников (автопоиск RSS, HTML-адаптеры) не ломает уже настроенный
каскад, пока их кто-то не проранжирует явно.
"""
from __future__ import annotations

import csv
from urllib.parse import urlparse

from .config import SOURCES_DIR

PRIORITY_CSV = SOURCES_DIR / "first_channel_priority.csv"

# Порядок каскада: чем меньше индекс, тем выше приоритет при отборе.
CASCADE_ORDER = ["A", "B", "C", "UNRANKED", "NO"]

_cache: dict[str, dict] | None = None


def _domain(url: str) -> str:
    if not url:
        return ""
    return urlparse(url.strip()).netloc.replace("www.", "")


def _load() -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache
    _cache = {}
    if not PRIORITY_CSV.exists():
        return _cache
    with open(PRIORITY_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("domain", "").strip()
            if d:
                _cache[d] = row
    return _cache


def reload() -> None:
    """Сбросить кеш — используется после обновления CSV (например, из UI)."""
    global _cache
    _cache = None


def get_priority(rss_url: str) -> str:
    """A/B/C/NO/UNRANKED для источника по его URL (сопоставление по домену)."""
    mapping = _load()
    row = mapping.get(_domain(rss_url))
    if not row:
        return "UNRANKED"
    p = (row.get("priority") or "").strip().upper()
    return p if p in ("A", "B", "C", "NO") else "UNRANKED"


def get_priority_row(rss_url: str) -> dict | None:
    """Полная строка ранжирования (с global_importance, priority_reason) или None."""
    return _load().get(_domain(rss_url))


def cascade_rank(priority: str) -> int:
    """Число для сортировки — меньше = выше приоритет."""
    try:
        return CASCADE_ORDER.index(priority)
    except ValueError:
        return len(CASCADE_ORDER)
