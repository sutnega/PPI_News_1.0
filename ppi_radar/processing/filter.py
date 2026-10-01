"""
Тематический rule-based фильтр (без ИИ): отсев нерелевантных записей
(вакансии, реклама, юбилеи) и записей вне временного окна, плюс
дедупликация RSS + headless-источников по ссылке.

Это ЧЕСТНО остаётся rule-based — как и в оригинальном filter_and_score.py.
Оценку важности (global_score/russia_score) этот модуль НЕ делает —
за это отвечает processing.editor (LLM-редактор), это разные задачи.
"""
from __future__ import annotations

import json

from ..config import DATA_DIR

FILTERED_OUTPUT = DATA_DIR / "filtered.json"

# Источники, целиком посвящённые ЦБП — ключевые слова для них не нужны,
# тема = сам источник (название организации прямо об этом говорит).
DEDICATED_SOURCES = {
    "SRC-0301", "SRC-0302", "SRC-0303", "SRC-0306", "SRC-0307", "SRC-0309",
    "SRC-0310", "SRC-0311", "SRC-0336", "SRC-0363", "SRC-0370", "SRC-0375",
    "SRC-0388",
    # Из headless-источников — ТОЛЬКО реально узкоотраслевые по своей природе:
    "SRC-0364",  # CPPRI (Central Pulp & Paper Research Institute)
    # ВАЖНО: China Paper Association (SRC-0305/SRC-0369, chinappi.org) убран
    # отсюда осознанно. Проверка реально собранных данных показала, что сайт
    # сейчас отдаёт совсем не отраслевой контент (внутрипартийные документы,
    # дисциплинарные разбирательства) — видимо, страница/раздел сайта
    # изменились. Раньше источник считался "отраслевым по умолчанию" и
    # проходил мимо тематического фильтра целиком — из-за этого весь мусор
    # уходил прямиком в LLM на оценку. Теперь он проверяется по ключевым
    # словам как любой другой источник (см. китайские ключевые слова ниже).
    # Сам сайт/селектор парсера тоже стоит перепроверить вручную с боевой
    # машины — доступность и вёрстка зависят от IP/гео (см. README).
    #
    # CAPMAS (SRC-0378, статведомство Египта), ECC Ethiopia (SRC-0382,
    # таможня), BRIN Indonesia (SRC-0389, научный институт по всем
    # направлениям) и PIB/Ministry of Commerce India (SRC-0360/SRC-0361,
    # общие пресс-релизы министерства) — это ОБЩИЕ государственные
    # источники, не узкоотраслевые. Их новости обязаны проходить проверку
    # по ключевым словам как любой другой источник, иначе в дайджест
    # попадает всё подряд (разрешения на работу, дипломатия и т.п.).
}

KEYWORDS = [
    "pulp", "paper", "paperboard", "cellulose", "tissue", "corrugat", "packaging",
    "forestry", "forest product", "wood fiber", "wood fibre", "newsprint", "kraft",
    "recycled fiber", "recovered paper", "waste paper", "board mill", "paper mill",
    "целлюлоз", "бумаг", "картон", "лесопром", "древесин", "лесн", "цбк", "цбп",
    "макулатур", "гофрокартон", "лесозагот",
    # ID (для BRIN — теперь проходит общий фильтр, а не освобождён от него)
    "kertas", "selulosa", "karton", "kemasan", "bubur kertas",
    # ZH (для chinappi.org и других китайских источников — без этого
    # весь генуинный китайский контент про бумагу отсеивался бы наравне
    # с мусором, потому что EN/RU ключевые слова не матчатся с иероглифами)
    "纸", "造纸", "纸浆", "包装", "纸业", "纸板", "森林",
]

BLOCKED_PHRASES = [
    "job vacancy", "career opportunity", "happy anniversary", "photo gallery",
    "вакансия", "поздравляем", "с юбилеем",
]


def is_relevant(title: str, summary: str, source_id: str) -> bool:
    text = f"{title} {summary}".lower()
    if any(bp in text for bp in BLOCKED_PHRASES):
        return False
    if source_id in DEDICATED_SOURCES:
        return True
    return any(kw in text for kw in KEYWORDS)


def filter_items(items: list[dict]) -> list[dict]:
    filtered, _ = filter_items_with_stats(items)
    return filtered


def filter_items_with_stats(items: list[dict]) -> tuple[list[dict], dict]:
    """
    То же самое, что filter_items(), но дополнительно считает, на каком
    именно шаге отсеялась каждая запись — чтобы можно было ответить на
    вопрос "почему из 246 осталось 7", а не гадать. Плюс полная разбивка
    по каждому source_id (сколько собрано / прошло / отсеяно и почему) —
    та же группировка, что раньше была видна только в консоли.
    """
    stats = {
        "total": len(items),
        "dropped_outside_window": 0,
        "dropped_no_title": 0,
        "dropped_duplicate_link": 0,
        "dropped_not_relevant": 0,
        "passed": 0,
    }

    per_source: dict[str, dict] = {}

    def _get_source_row(it: dict) -> dict:
        sid = it.get("source_id", "?")
        if sid not in per_source:
            per_source[sid] = {
                "source_id": sid, "country": it.get("country", "?"),
                "collected": 0, "passed": 0, "outside_window": 0,
                "no_title": 0, "duplicate": 0, "not_relevant": 0,
            }
        return per_source[sid]

    def _drop(reason_key: str, source_field: str, it: dict) -> None:
        stats[reason_key] += 1
        _get_source_row(it)[source_field] += 1

    seen_links = set()
    filtered = []
    for it in items:
        _get_source_row(it)["collected"] += 1
        if not it.get("in_window"):
            _drop("dropped_outside_window", "outside_window", it)
            continue
        if not it.get("title"):
            _drop("dropped_no_title", "no_title", it)
            continue
        link = it.get("link")
        if link and link in seen_links:
            _drop("dropped_duplicate_link", "duplicate", it)
            continue
        if not is_relevant(it["title"], it.get("summary", ""), it.get("source_id", "")):
            _drop("dropped_not_relevant", "not_relevant", it)
            continue
        filtered.append(it)
        _get_source_row(it)["passed"] += 1
        if link:
            seen_links.add(link)

    stats["passed"] = len(filtered)
    # Сортировка: сначала источники, которые вообще ничего не пропустили
    # (самые "подозрительные" — либо стабильно вне темы, либо давно не
    # обновлялись/сломались), потом по числу собранного.
    stats["per_source"] = sorted(
        per_source.values(), key=lambda r: (r["passed"] > 0, -r["collected"])
    )
    return filtered, stats


def run(rss_items: list[dict] | None = None, headless_items: list[dict] | None = None) -> list[dict]:
    filtered, _ = run_with_stats(rss_items, headless_items)
    return filtered


def run_with_stats(rss_items: list[dict] | None = None,
                    headless_items: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Собирает вместе RSS + headless результаты, фильтрует, сохраняет, возвращает статистику воронки."""
    if rss_items is None:
        rss_path = DATA_DIR / "rss_collected_raw.json"
        rss_items = json.loads(rss_path.read_text(encoding="utf-8"))["items"] if rss_path.exists() else []
    if headless_items is None:
        headless_path = DATA_DIR / "headless_collected_raw.json"
        headless_items = json.loads(headless_path.read_text(encoding="utf-8")) if headless_path.exists() else []

    combined = list(rss_items) + list(headless_items)
    filtered, stats = filter_items_with_stats(combined)

    by_country: dict[str, list[dict]] = {}
    for it in filtered:
        by_country.setdefault(it.get("country", "?"), []).append(it)

    print(f"Собрано всего: {stats['total']}")
    print(f"  - отсеяно вне временного окна: {stats['dropped_outside_window']}")
    print(f"  - отсеяно без заголовка: {stats['dropped_no_title']}")
    print(f"  - отсеяно как дубль по ссылке: {stats['dropped_duplicate_link']}")
    print(f"  - отсеяно как нерелевантное (не про ЦБП): {stats['dropped_not_relevant']}")
    print(f"Прошло фильтр: {stats['passed']}")
    print("\nРазбивка по источникам (собрано / прошло):")
    for row in stats["per_source"]:
        print(f"    [{row['source_id']}] {row['country']}: собрано {row['collected']}, "
              f"прошло {row['passed']} (вне окна {row['outside_window']}, "
              f"не по теме {row['not_relevant']}, дубли {row['duplicate']})")
    for country, arts in sorted(by_country.items()):
        print(f"--- {country} ({len(arts)}) ---")
        for a in arts:
            print(f"  [{a['source_id']}] {a['title'][:90]}")

    FILTERED_OUTPUT.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")
    return filtered, stats


if __name__ == "__main__":
    run()
