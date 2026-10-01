"""
Журнал редакторских решений — approve/reject/replace по каждому кандидату
при отборе дайджеста (см. TZ_PPI_Radar_AI_pipeline, раздел 17 "Логи и
обратная связь").

Смысл: сохранить, что редактор реально выбрал/отклонил, чтобы через
30-90 дней можно было посчитать PPI Yield для каждого источника —
насколько часто его новости реально доходят до публикации — и
скорректировать A/B/C по фактической полезности, а не по предположениям
на старте. Без этого журнала такой анализ невозможен задним числом.

Формат — тот же JSON Lines, что и в archive.py: дописывать дёшево,
ничего не перезаписывается.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import DATA_DIR

DECISIONS_PATH = DATA_DIR / "editorial_decisions.jsonl"


def log_decisions(candidates: list[dict], decision_source: str = "auto_cascade") -> int:
    """
    candidates — список кандидатов в формате _candidate_view() из editor.py
    (обязательно с полями selected, reason, source_id, channel_priority,
    country). decision_source — "auto_cascade" (автоматический отбор) или
    "manual_checklist" (человек поправил галочки в UI).
    """
    now = datetime.now(timezone.utc).isoformat()
    with open(DECISIONS_PATH, "a", encoding="utf-8") as f:
        for c in candidates:
            record = {
                "logged_at": now,
                "decision_source": decision_source,
                "decision": "approve" if c.get("selected") else "reject",
                "reason": c.get("reason", ""),
                "source_id": c.get("source_id", ""),
                "channel_priority": c.get("channel_priority", "UNRANKED"),
                "country": c.get("country", ""),
                "headline_ru": c.get("headline_ru", ""),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(candidates)


def load_decisions(limit: int | None = None) -> list[dict]:
    if not DECISIONS_PATH.exists():
        return []
    records = []
    with open(DECISIONS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records[-limit:] if limit else records


def source_yield_stats() -> list[dict]:
    """
    PPI Yield по источнику: доля решений approve среди всех решений по
    этому source_id. Считать полноценно есть смысл не раньше, чем
    накопится история за 30-90 дней — сейчас функция просто честно
    отдаёт то, что реально есть в журнале на текущий момент.
    """
    records = load_decisions()
    by_source: dict[str, dict] = {}
    for r in records:
        sid = r.get("source_id") or "?"
        row = by_source.setdefault(sid, {"source_id": sid, "approved": 0, "rejected": 0,
                                          "channel_priority": r.get("channel_priority", "UNRANKED")})
        if r.get("decision") == "approve":
            row["approved"] += 1
        else:
            row["rejected"] += 1
    result = []
    for row in by_source.values():
        total = row["approved"] + row["rejected"]
        row["total"] = total
        row["yield_pct"] = round(100 * row["approved"] / total, 1) if total else 0.0
        result.append(row)
    return sorted(result, key=lambda r: -r["total"])
