"""
Единый журнал ВСЕХ ошибок по всему проекту — в одном файле.

Раньше ошибки были видны только в консоли (и терялись, как только её
закрыли/прокрутили): ошибки парсинга RSS/HTML, недоступные сайты, отказы
LLM-провайдеров — каждый модуль печатал своё, нигде не собиралось вместе.

log_error() дописывает одну строку JSON на ошибку в data/logs/all_errors.jsonl
— копится нарастающим итогом (как archive.py и editorial_log.py), не
перезаписывается. Формат: {timestamp, component, error_type, message, **context}.

Использование в месте отлова ошибки:
    from ..error_log import log_error
    ...
    except Exception as e:
        log_error("rss", "fetch_or_parse_error", str(e), source_id=sid, url=url)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import LOGS_DIR

ERROR_LOG_PATH = LOGS_DIR / "all_errors.jsonl"


def log_error(component: str, error_type: str, message: str, **context) -> None:
    """
    component — модуль-источник: "rss" / "headless" / "html_adapters" /
                "llm_editor" / "images" / "telegram" / "discover_rss" и т.п.
    error_type — короткий машинный код ошибки (для группировки/фильтрации),
                например "fetch_error", "parse_error", "llm_chain_exhausted".
    message — человекочитаемый текст ошибки (обычно str(exception)).
    **context — что угодно дополнительное: source_id, url, provider, slug...
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "error_type": error_type,
        "message": message,
        **context,
    }
    try:
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Логирование не должно само по себе ронять пайплайн — если писать
        # в лог не удалось (диск и т.п.), тихо продолжаем.
        pass


def load_errors(limit: int | None = None, component: str | None = None) -> list[dict]:
    if not ERROR_LOG_PATH.exists():
        return []
    records = []
    with open(ERROR_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if component and rec.get("component") != component:
                continue
            records.append(rec)
    if limit:
        records = records[-limit:]
    return records


def error_stats() -> dict:
    records = load_errors()
    from collections import Counter
    by_component = Counter(r.get("component", "?") for r in records)
    by_type = Counter(r.get("error_type", "?") for r in records)
    return {
        "total": len(records),
        "by_component": dict(sorted(by_component.items(), key=lambda x: -x[1])),
        "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "newest": records[-1] if records else None,
    }


def clear_errors() -> None:
    """Только по явному запросу пользователя — не вызывается автоматически."""
    if ERROR_LOG_PATH.exists():
        ERROR_LOG_PATH.unlink()
