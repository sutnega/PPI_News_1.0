"""
PPI Global Radar — единая точка входа.

Запуск полного цикла:
    python -m ppi_radar.pipeline all

Запуск отдельного этапа:
    python -m ppi_radar.pipeline collect       # RSS + headless-источники
    python -m ppi_radar.pipeline filter        # тематический фильтр
    python -m ppi_radar.pipeline edit          # LLM-скоринг + отбор дайджеста
    python -m ppi_radar.pipeline images        # og:image
    python -m ppi_radar.pipeline cards         # сборка HTML-карточек
    python -m ppi_radar.pipeline publish              # dry-run (по умолчанию)
    python -m ppi_radar.pipeline publish --publish     # реальная отправка в Telegram

Премодерация: между `cards` и реальной публикацией стоит явный ручной шаг —
посмотреть карточки в data/tg_cards/ и только потом запускать publish --publish.
"""
from __future__ import annotations

import argparse
import json
from datetime import date

from . import sources
from .collectors.headless_news import collect_headless
from .collectors.html_adapters import _adapter_slugs as html_adapter_slugs, collect_html_adapters, is_available as html_adapters_available
from .collectors.rss import collect_rss
from .config import BRICS_PLUS_COUNTRIES, DATA_DIR
from .processing.editor import score_items, select_daily_digest
from .processing.filter import run as filter_run
from .processing.images import attach_images
from .publishing.cards import build_cards, save_cards
from .publishing.telegram import publish_cards


def cmd_status(_args) -> None:
    cov = sources.coverage_summary()
    print("Охват базы источников (v9):")
    print(f"  Всего: {cov['total']}")
    print(f"  Рабочих (READY_FOR_TECH_TEST + VALIDATED_WORKING): {cov['working']}")
    print(f"  Требуют доразведки: {cov['discovery_required']}")
    print(f"  Заблокировано/мертво: {cov['blocked_or_dead']}")
    rss_count = len(sources.extract_rss_sources())
    print(f"  Из них RSS-источников: {rss_count}")
    print(f"  Остальные рабочие идут через headless/API-парсеры (см. collectors/headless_news.py)")
    print(f"  HTML-адаптеры: {len(html_adapter_slugs())} источников вендорено в проект "
          f"(ppi_radar/vendor/ppi_html_adapters/), доступны сразу")


def cmd_collect(args) -> None:
    print("== Сбор: RSS ==")
    collect_rss(window_hours=args.window_hours)
    if not args.skip_headless:
        print("\n== Сбор: headless/API-источники ==")
        collect_headless()
    else:
        print("\n(headless-источники пропущены: --skip-headless)")
    if getattr(args, "html_adapters", False):
        print("\n== Сбор: HTML-адаптеры (21 источник) ==")
        collect_html_adapters()
    elif not html_adapters_available():
        print("\n(HTML-адаптеры пропущены: пакет ppi_html_adapters не установлен)")


def cmd_filter(_args) -> None:
    filter_run()


def cmd_edit(args) -> None:
    filtered_path = DATA_DIR / "filtered.json"
    if not filtered_path.exists():
        raise SystemExit("Нет data/filtered.json — сначала запустите: pipeline filter")
    filtered = json.loads(filtered_path.read_text(encoding="utf-8"))
    scored = score_items(filtered)
    digest = select_daily_digest(scored, BRICS_PLUS_COUNTRIES, per_country=args.per_country,
                                  max_world=args.max_world, russia_count=args.russia_count)
    print(f"В дневной дайджест отобрано: {len(digest)} карточек")


def cmd_images(_args) -> None:
    digest_path = DATA_DIR / "digest_cards.json"
    if not digest_path.exists():
        raise SystemExit("Нет data/digest_cards.json — сначала запустите: pipeline edit")
    data = json.loads(digest_path.read_text(encoding="utf-8"))
    data["items"] = attach_images(data["items"])
    digest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    found = sum(1 for i in data["items"] if i.get("image_url"))
    print(f"Картинки найдены для {found} из {len(data['items'])} карточек")


def cmd_cards(args) -> None:
    digest_path = DATA_DIR / "digest_cards.json"
    if not digest_path.exists():
        raise SystemExit("Нет data/digest_cards.json — сначала запустите: pipeline edit")
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    issue_date = args.date or date.today().strftime("%d.%m.%Y")
    cards = build_cards(digest, issue_date=issue_date)
    save_cards(cards)


def cmd_publish(args) -> None:
    from .publishing.cards import CARDS_TXT

    digest_path = DATA_DIR / "digest_cards.json"
    if not digest_path.exists():
        raise SystemExit("Нет data/digest_cards.json — сначала пройдите этапы edit -> images -> cards")
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    issue_date = args.date or date.today().strftime("%d.%m.%Y")
    cards = build_cards(digest, issue_date=issue_date)
    publish_cards(cards, dry_run=not args.publish)


def cmd_all(args) -> None:
    cmd_collect(args)
    cmd_filter(args)
    cmd_edit(args)
    cmd_images(args)
    cmd_cards(args)
    cmd_publish(args)


def main() -> None:
    parser = argparse.ArgumentParser(description="PPI Global Radar — единый пайплайн")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="сводка по базе источников").set_defaults(func=cmd_status)

    p_collect = sub.add_parser("collect", help="собрать RSS + headless-источники")
    p_collect.add_argument("--window-hours", type=int, default=168)
    p_collect.add_argument("--skip-headless", action="store_true")
    p_collect.add_argument("--html-adapters", action="store_true",
                            help="дополнительно собрать 21 источник через пакет ppi_html_adapters (если установлен)")
    p_collect.set_defaults(func=cmd_collect)

    sub.add_parser("filter", help="тематический фильтр + дедупликация").set_defaults(func=cmd_filter)
    p_edit = sub.add_parser("edit", help="LLM-скоринг, перевод, отбор дайджеста")
    p_edit.add_argument("--per-country", type=int, default=1, help="сколько новостей на страну БРИКС+, кроме России (по умолчанию 1)")
    p_edit.add_argument("--russia-count", type=int, default=2, help="сколько новостей по России отдельно (по умолчанию 2)")
    p_edit.add_argument("--max-world", type=int, default=3, help="сколько мировых новостей вне БРИКС+ (по умолчанию 3)")
    p_edit.set_defaults(func=cmd_edit)
    sub.add_parser("images", help="проверка og:image").set_defaults(func=cmd_images)

    p_cards = sub.add_parser("cards", help="сборка HTML-карточек")
    p_cards.add_argument("--date", help="дата выпуска, напр. 19.07.2026")
    p_cards.set_defaults(func=cmd_cards)

    p_publish = sub.add_parser("publish", help="публикация в Telegram (по умолчанию dry-run)")
    p_publish.add_argument("--publish", action="store_true", help="реально отправить в канал")
    p_publish.add_argument("--date", help="дата выпуска, напр. 19.07.2026")
    p_publish.set_defaults(func=cmd_publish)

    p_all = sub.add_parser("all", help="весь цикл целиком")
    p_all.add_argument("--window-hours", type=int, default=168)
    p_all.add_argument("--skip-headless", action="store_true")
    p_all.add_argument("--html-adapters", action="store_true")
    p_all.add_argument("--publish", action="store_true")
    p_all.add_argument("--date", help="дата выпуска")
    p_all.add_argument("--per-country", type=int, default=1)
    p_all.add_argument("--russia-count", type=int, default=2)
    p_all.add_argument("--max-world", type=int, default=3)
    p_all.set_defaults(func=cmd_all)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
