"""
Публикация карточек в Telegram-канал через Bot API.

ВАЖНО и отличие от оригинала: telegram_test_post.py в экспорте НИЧЕГО не
отправлял, несмотря на то что README это утверждал — там только запись
текста в файл. Здесь — настоящий вызов sendMessage/sendPhoto.

Премодерация — явное правило проекта (зафиксировано в README экспорта):
публикация НЕ происходит без явного флага --publish в CLI (см. pipeline.py).
По умолчанию этот модуль только показывает, что было бы отправлено (dry-run).

ВАЖНО про конфигурацию: токен и chat_id читаются из ppi_radar.config
ДИНАМИЧЕСКИ при каждом вызове (через `cfg.TELEGRAM_BOT_TOKEN`), а не как
значения по умолчанию в сигнатуре функций. Если бы они были захардкожены
в default-параметрах, Python вычислил бы их один раз при загрузке модуля —
и в веб-интерфейсе (Streamlit-процесс живёт долго и не перезапускается на
каждое действие) изменения в .env через страницу «Настройки» никогда бы
не подхватились без полного перезапуска приложения.
"""
from __future__ import annotations

import time

import requests

from .. import config as cfg
from ..error_log import log_error

API_BASE = "https://api.telegram.org/bot{token}"


def _check_token() -> None:
    if not cfg.TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан. Получите токен: @BotFather -> /newbot, и пропишите "
            "его в .env (см. .env.example)."
        )


def _check_chat_id(chat_id: str) -> None:
    if not chat_id:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID не задан. Для публичного канала используйте @username "
            "(например @PPIGlobalRadar), для приватного — числовой ID. Пропишите в .env."
        )


def send_message(text: str, chat_id: str | None = None) -> dict:
    chat_id = chat_id or cfg.TELEGRAM_CHAT_ID
    _check_token()
    _check_chat_id(chat_id)
    url = API_BASE.format(token=cfg.TELEGRAM_BOT_TOKEN) + "/sendMessage"
    resp = requests.post(url, data={
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }, timeout=20)
    resp.raise_for_status()
    return resp.json()


def send_photo(photo_url: str, caption: str, chat_id: str | None = None) -> dict:
    chat_id = chat_id or cfg.TELEGRAM_CHAT_ID
    _check_token()
    _check_chat_id(chat_id)
    url = API_BASE.format(token=cfg.TELEGRAM_BOT_TOKEN) + "/sendPhoto"
    resp = requests.post(url, data={
        "chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML",
    }, timeout=20)
    resp.raise_for_status()
    return resp.json()


def publish_cards(cards: list[tuple[str, str, str | None]], dry_run: bool = True,
                   delay_seconds: float = 2.0) -> None:
    """
    cards: список (название, html_текст, image_url_или_None) — формат
    из publishing.cards.build_cards().
    """
    if dry_run:
        print("=== DRY RUN: ничего не отправляется в Telegram ===")
        for name, text, image_url in cards:
            print(f"\n--- {name} (image={'да' if image_url else 'нет'}) ---")
            print(text[:300] + ("..." if len(text) > 300 else ""))
        print(f"\nВсего карточек к публикации: {len(cards)}. "
              f"Для реальной отправки запустите с --publish.")
        return

    _check_token()
    _check_chat_id(cfg.TELEGRAM_CHAT_ID)
    for name, text, image_url in cards:
        try:
            if image_url:
                result = send_photo(image_url, text)
            else:
                result = send_message(text)
            ok = result.get("ok", False)
            print(f"{'OK' if ok else 'FAIL'}: {name} -> {result if not ok else 'отправлено'}")
        except Exception as e:
            print(f"ERROR отправки {name}: {e}")
            log_error("telegram", "send_error", str(e), card=name)
        time.sleep(delay_seconds)  # не спамить Telegram API
