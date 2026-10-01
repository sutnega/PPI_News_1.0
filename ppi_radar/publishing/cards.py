"""
Сборка готовых карточек в HTML-разметку Telegram из дневного дайджеста.
Было: build_telegram_cards.py, захардкоженный на конкретную дату/путь.
"""
from __future__ import annotations

import json

from ..config import CARDS_DIR, COUNTRY_FLAGS, DATA_DIR

CARDS_TXT = DATA_DIR / "telegram_final_cards.txt"

TELEGRAM_LIMIT = 4096


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_cards(digest: dict, issue_date: str) -> list[tuple[str, str, str | None]]:
    """
    Возвращает список (country_or_'intro', html_text, image_url).
    """
    cards: list[tuple[str, str, str | None]] = []

    intro = (
        f"📡 <b>PPI Global Radar — выпуск за {issue_date}</b>\n"
        "Дневная подборка новостей целлюлозно-бумажной отрасли по странам БРИКС+ "
        "и главные мировые события. Экспертный комментарий: влияние на мир и на Россию."
    )
    cards.append(("intro", intro, None))

    for item in digest["items"]:
        if item.get("include") is False:
            continue
        country = item.get("country", "?")
        flag = COUNTRY_FLAGS.get(country, "🏳")
        lines = [f"{flag} <b>{esc(country)}</b>", "", f"<b>{esc(item.get('headline_ru', ''))}</b>"]
        if item.get("summary_250"):
            lines += ["", esc(item["summary_250"])]
        if item.get("caveat"):
            lines += ["", f"⚠️ {esc(item['caveat'])}"]
        lines += ["", f"🌍 <b>Мир:</b> {esc(item.get('world_comment', ''))}"]
        lines += ["", f"🇷🇺 <b>Россия:</b> {esc(item.get('russia_comment', ''))}"]
        sources = item.get("sources", [])
        if sources:
            src_links = ", ".join(f'<a href="{s}">{i + 1}</a>' for i, s in enumerate(sources))
            lines += ["", f"📎 Источники: {src_links}"]
        text = "\n".join(lines)
        if len(text) > TELEGRAM_LIMIT:
            print(f"ВНИМАНИЕ: карточка {country} превышает лимит Telegram ({len(text)} > {TELEGRAM_LIMIT})")
        cards.append((country, text, item.get("image_url")))

    return cards


def save_cards(cards: list[tuple[str, str, str | None]]) -> None:
    total = 0
    with open(CARDS_TXT, "w", encoding="utf-8") as out:
        for name, text, image_url in cards:
            total += len(text)
            out.write(f"=== {name} (len={len(text)}, image={image_url}) ===\n{text}\n\n")
    for i, (name, text, image_url) in enumerate(cards):
        (CARDS_DIR / f"{i:02d}_{name}.txt").write_text(text, encoding="utf-8")
    print(f"Сохранено карточек: {len(cards)}, суммарно символов: {total}")
    print(f" -> {CARDS_TXT}")
    print(f" -> {CARDS_DIR}/")


if __name__ == "__main__":
    from datetime import date

    digest_path = DATA_DIR / "digest_cards.json"
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    cards = build_cards(digest, issue_date=date.today().strftime("%d.%m.%Y"))
    save_cards(cards)
