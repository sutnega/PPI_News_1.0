"""
PPI Global Radar — веб-интерфейс.

Запуск:
    streamlit run app.py

Оборачивает тот же ppi_radar/pipeline.py в кликабельный UI: те же этапы
(сбор -> фильтр -> редактура -> картинки -> карточки -> публикация),
но с таблицами, прогресс-барами и предпросмотром карточек вместо
командной строки.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from ppi_radar import config as cfg
from ppi_radar import sources as sources_mod
from ppi_radar.config import (
    ANTHROPIC_API_KEY, CARDS_DIR, DATA_DIR, LLM_PROVIDER, ROOT_DIR,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BRICS_PLUS_COUNTRIES,
)
from ppi_radar.processing.editor import provider_ready

st.set_page_config(page_title="PPI Global Radar", page_icon="📡", layout="wide")

RSS_RAW = DATA_DIR / "rss_collected_raw.json"
HEADLESS_RAW = DATA_DIR / "headless_collected_raw.json"
FILTERED = DATA_DIR / "filtered.json"
SCORED = DATA_DIR / "scored.json"
DIGEST = DATA_DIR / "digest_cards.json"
CANDIDATES = DATA_DIR / "candidates_by_country.json"
ENV_PATH = ROOT_DIR / ".env"


# --------------------------------------------------------------------------- helpers
def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_env_value(key: str, value: str) -> None:
    """Обновляет (или добавляет) одну переменную в .env, не трогая остальные."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def mask(secret: str) -> str:
    if not secret:
        return "не задан"
    return secret[:4] + "…" + secret[-4:] if len(secret) > 10 else "задан"


# --------------------------------------------------------------------------- sidebar
st.sidebar.title("📡 PPI Global Radar")
st.sidebar.caption("Мониторинг новостей ЦБП и упаковки · БРИКС+")

page = st.sidebar.radio(
    "Этапы",
    ["📊 Обзор", "🌐 Сбор", "🔎 Фильтр", "🤖 Редактура", "🖼️ Картинки",
     "📰 Карточки и публикация", "🔬 Источники", "⚙️ Настройки"],
)

st.sidebar.divider()
st.sidebar.caption(f"Telegram-токен: {mask(TELEGRAM_BOT_TOKEN)}")
from ppi_radar.processing.llm_providers import get_provider_chain

try:
    _chain_display = " → ".join(get_provider_chain())
except ValueError:
    _chain_display = LLM_PROVIDER
st.sidebar.caption(f"LLM: {_chain_display} ({'настроен' if provider_ready() else 'не настроен'})")

# --------------------------------------------------------------------------- Обзор
if page == "📊 Обзор":
    st.title("Обзор проекта")

    from ppi_radar.collectors.discover_rss import load_discovered

    cov = sources_mod.coverage_summary()
    rss_sources = sources_mod.extract_rss_sources()
    discovered_count = len(load_discovered())
    official_rss_count = len(rss_sources) - discovered_count

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Всего в официальной базе", cov["total"])
    c2.metric("Рабочих в официальной базе", cov["working"])
    c3.metric("Требуют доразведки", cov["discovery_required"])
    c4.metric("Заблокировано/мертво", cov["blocked_or_dead"])

    st.caption(
        f"Источников для сбора новостей сейчас {len(rss_sources)} через RSS "
        f"({official_rss_count} из официальной базы v9 + {discovered_count} автонайденных/"
        f"импортированных дополнительно, см. вкладку «🔬 Источники») — плюс несколько "
        f"headless/API-парсеров для источников без RSS."
    )

    from collections import Counter
    tier_counts = Counter(r.get("channel_priority", "UNRANKED") for r in rss_sources)
    if any(tier_counts.get(t, 0) for t in ("A", "B", "C", "NO")):
        tc1, tc2, tc3, tc4, tc5 = st.columns(5)
        tc1.metric("🟢 Уровень A", tier_counts.get("A", 0))
        tc2.metric("🟡 Уровень B", tier_counts.get("B", 0))
        tc3.metric("🟠 Уровень C", tier_counts.get("C", 0))
        tc4.metric("⚫ NO (не в ranking)", tier_counts.get("NO", 0))
        tc5.metric("⚪ Не проранжировано", tier_counts.get("UNRANKED", 0))
        st.caption("Приоритет — каскад для отбора дайджеста (🤖 Редактура): сначала A, затем B, затем C. "
                   "NO продолжает собираться в архив, но никогда не участвует в конкурсе за место в дайджесте.")

    st.divider()
    st.subheader("Журнал редакторских решений")
    from ppi_radar.editorial_log import load_decisions, source_yield_stats
    decisions = load_decisions()
    st.caption(
        f"Каждый отбор дайджеста (автоматический и ручной через чек-лист) логируется — "
        f"сейчас в журнале {len(decisions)} решений. Это основа для будущего PPI Yield "
        f"(доля решений approve на источник) — по нему через 30-90 дней можно будет "
        f"скорректировать A/B/C по факту, а не по предположениям на старте."
    )
    yield_stats = source_yield_stats()
    if yield_stats:
        with st.expander(f"📈 PPI Yield по источникам ({len(yield_stats)} источников с историей)"):
            st.dataframe(pd.DataFrame(yield_stats)[["source_id", "channel_priority", "approved", "rejected", "yield_pct"]],
                         width='stretch', height=300)

    st.divider()
    st.subheader("🪵 Журнал всех ошибок проекта")
    from ppi_radar.error_log import clear_errors, error_stats, load_errors
    estats = error_stats()
    st.caption(
        f"Единый файл на все ошибки пайплайна — сбор (RSS/headless/адаптеры), редактор (отказы "
        f"LLM-провайдеров), картинки, публикация. Сейчас в журнале **{estats['total']}** записей. "
        f"Файл: `data/logs/all_errors.jsonl`, копится нарастающим итогом — не перезаписывается."
    )
    if estats["total"]:
        ec1, ec2 = st.columns(2)
        with ec1:
            st.markdown("**По компоненту:**")
            st.dataframe(pd.DataFrame(list(estats["by_component"].items()), columns=["компонент", "ошибок"]),
                         width='stretch', height=200)
        with ec2:
            st.markdown("**По типу:**")
            st.dataframe(pd.DataFrame(list(estats["by_type"].items()), columns=["тип", "ошибок"]),
                         width='stretch', height=200)

        with st.expander(f"Последние 200 ошибок (из {estats['total']})"):
            errors = load_errors(limit=200)
            st.dataframe(pd.DataFrame(errors), width='stretch', height=400)

        if st.checkbox("Показать «Очистить журнал ошибок» (необратимо)"):
            if st.button("🗑️ Очистить журнал ошибок", type="secondary"):
                clear_errors()
                st.success("Журнал ошибок очищен.")
                st.rerun()
    else:
        st.caption("Ошибок пока не зафиксировано.")

    st.divider()
    st.subheader("Архив всех собранных новостей")
    from ppi_radar.archive import archive_stats
    astats = archive_stats()
    st.caption(
        f"В отличие от data/*.json (перезаписывается на каждом прогоне), архив копится "
        f"навсегда — сейчас в нём **{astats['total']}** новостей за всё время "
        f"(с {astats['oldest'][:10] if astats['oldest'] else '—'} по "
        f"{astats['newest'][:10] if astats['newest'] else '—'})."
    )
    if astats["by_country"]:
        top_countries = dict(list(astats["by_country"].items())[:10])
        st.bar_chart(top_countries)

    st.divider()
    st.subheader("Состояние данных пайплайна")

    stages = [
        ("Сбор RSS", RSS_RAW), ("Сбор headless", HEADLESS_RAW),
        ("Фильтр", FILTERED), ("Скоринг/редактура", SCORED),
        ("Дневной дайджест", DIGEST),
    ]
    cols = st.columns(len(stages))
    for col, (label, path) in zip(cols, stages):
        with col:
            if path.exists():
                data = load_json(path)
                count = len(data["items"]) if isinstance(data, dict) and "items" in data else len(data)
                st.success(f"**{label}**\n\n{count} записей")
            else:
                st.warning(f"**{label}**\n\nещё не запускалось")

    if not provider_ready():
        st.info(f"⚠️ LLM-провайдер '{LLM_PROVIDER}' не настроен — редактура (шаг 🤖) будет "
                f"использовать грубую эвристику вместо реальной оценки важности. Настройте "
                f"бесплатный провайдер (Groq/Gemini/Ollama) на вкладке «⚙️ Настройки».")
    if not TELEGRAM_BOT_TOKEN:
        st.info("⚠️ TELEGRAM_BOT_TOKEN не задан — публикация в канал будет недоступна "
                "(предпросмотр карточек по-прежнему работает).")

# --------------------------------------------------------------------------- Сбор
elif page == "🌐 Сбор":
    st.title("Сбор новостей")
    st.caption("RSS — быстро и надёжно. Headless — медленнее, требует установленный Playwright/Chromium. "
               "HTML-адаптеры — 21 источник без RSS/API, вендорены в проект, установки не требуют.")

    st.subheader("Окно свежести")
    if "window_days" not in st.session_state:
        st.session_state["window_days"] = 7

    wcol1, wcol2, wcol3 = st.columns([3, 1, 1])
    with wcol1:
        window_days = st.number_input(
            "За сколько последних дней считать новости свежими", min_value=1, max_value=90,
            key="window_days",
            help="Влияет на все кнопки сбора ниже — и на «Собрать всё», и на отдельные источники.",
        )
    with wcol2:
        st.write("")  # выравнивание по высоте с number_input
        if st.button("📅 Неделя", width='stretch'):
            st.session_state["window_days"] = 7
            st.rerun()
    with wcol3:
        st.write("")
        if st.button("📅 Месяц", width='stretch'):
            st.session_state["window_days"] = 30
            st.rerun()

    window_hours = window_days * 24
    st.caption(f"Сейчас: {window_days} дн. (источники старше этого срока отсеются как неактуальные)")

    st.divider()

    if st.button("🚀 Собрать всё (RSS → Headless → HTML-адаптеры)", type="primary", width='stretch'):
        from ppi_radar.collectors.headless_news import collect_headless_with_stats
        from ppi_radar.collectors.html_adapters import collect_html_adapters
        from ppi_radar.collectors.rss import collect_rss

        # Намеренно последовательно, не параллельно: Playwright (headless-шаг)
        # рассчитан на работу в главном потоке процесса, а параллельный запуск
        # RSS/headless/адаптеров создавал бы гонку при записи в общий архив
        # (data/archive/news_archive.jsonl). Последовательно — медленнее, но
        # гарантированно не ломается.
        progress = st.progress(0.0, text="Собираю RSS...")
        total_items = 0
        try:
            payload = collect_rss(window_hours=window_hours)
            st.session_state["rss_per_source"] = payload.get("per_source", [])
            total_items += len(payload["items"])
            progress.progress(1 / 3, text=f"RSS готово ({len(payload['items'])} записей). Собираю headless...")

            items_h, per_source_h = collect_headless_with_stats()
            st.session_state["headless_per_source"] = per_source_h
            total_items += len(items_h)
            progress.progress(2 / 3, text=f"Headless готово ({len(items_h)} записей). Собираю HTML-адаптеры...")

            items_a, per_source_a = collect_html_adapters()
            st.session_state["html_adapters_per_source"] = per_source_a
            total_items += len(items_a)
            progress.progress(1.0, text="Готово")

            progress.empty()
            st.success(f"Собрано всего: {total_items} записей "
                       f"(RSS: {len(payload['items'])}, Headless: {len(items_h)}, Адаптеры: {len(items_a)})")
        except Exception as e:
            progress.empty()
            st.error(f"Ошибка на одном из шагов: {e}. То, что уже успело собраться до сбоя, сохранено — "
                     f"можно посмотреть в таблицах ниже и продолжить с шага «🔎 Фильтр».")

    st.divider()
    st.caption("Или запустите источники по отдельности (используют то же окно свежести сверху):")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("▶️ Собрать по RSS", width='stretch'):
            from ppi_radar.collectors.rss import collect_rss
            with st.spinner("Опрашиваю RSS-источники..."):
                try:
                    payload = collect_rss(window_hours=window_hours)
                    st.session_state["rss_per_source"] = payload.get("per_source", [])
                    st.success(f"Готово: {len(payload['items'])} записей, {len(payload['errors'])} ошибок")
                    if payload["errors"]:
                        st.dataframe(pd.DataFrame(payload["errors"]), width='stretch')
                except Exception as e:
                    st.error(f"Ошибка сбора RSS: {e}")

    with col2:
        st.write("Headless-источники (Китай, Индия, Египет, Эфиопия, Индонезия)")
        if st.button("▶️ Собрать headless/API-источники", width='stretch'):
            from ppi_radar.collectors.headless_news import collect_headless_with_stats
            with st.spinner("Рендерю страницы через Chromium — это может занять пару минут..."):
                try:
                    items, per_source = collect_headless_with_stats()
                    st.session_state["headless_per_source"] = per_source
                    st.success(f"Готово: {len(items)} записей")
                except Exception as e:
                    st.error(f"Ошибка: {e}\n\nПроверьте, что выполнено `playwright install chromium`.")

    with col3:
        st.write("HTML-адаптеры (21 источник: Segezha, Klabin, FT, Caixin и др.)")
        if st.button("▶️ Собрать через HTML-адаптеры", width='stretch'):
            from ppi_radar.collectors.html_adapters import collect_html_adapters
            with st.spinner("Обхожу 21 источник — доступность части из них зависит от IP/гео этой машины..."):
                try:
                    items, per_source = collect_html_adapters()
                    st.session_state["html_adapters_per_source"] = per_source
                    st.success(f"Готово: {len(items)} записей")
                except Exception as e:
                    st.error(f"Ошибка: {e}")

    st.divider()
    st.subheader("Разбивка по источникам — сколько реально отдал каждый")
    st.caption("Источники с 0 записей — это либо давно не обновлялись (проверьте вручную), либо сайт "
               "изменил вёрстку и парсер сломался (для headless/адаптеров), либо истёк срок жизни ссылки.")

    rss_ps = st.session_state.get("rss_per_source")
    if not rss_ps:
        rss_raw = load_json(RSS_RAW)
        rss_ps = rss_raw.get("per_source") if isinstance(rss_raw, dict) else None
    if rss_ps:
        df_rss = pd.DataFrame(rss_ps).sort_values("in_window_entries")
        st.markdown("**RSS-источники:**")
        st.dataframe(df_rss[["source_id", "country", "org", "total_entries", "in_window_entries", "status"]],
                     width='stretch', height=280)
        zero_rss = df_rss[df_rss["in_window_entries"] == 0]
        if len(zero_rss):
            st.caption(f"⚠️ {len(zero_rss)} RSS-источников не дали ни одной новости за окно свежести.")

    headless_ps = st.session_state.get("headless_per_source")
    if headless_ps:
        st.markdown("**Headless/API-источники:**")
        st.dataframe(pd.DataFrame(headless_ps)[["source_id", "country", "total_entries", "status"]],
                     width='stretch', height=200)

    html_ps = st.session_state.get("html_adapters_per_source")
    if html_ps:
        st.markdown("**HTML-адаптеры:**")
        st.dataframe(pd.DataFrame(html_ps)[["source_id", "country", "total_entries", "status"]],
                     width='stretch', height=200)

    st.divider()
    for label, path in [("RSS", RSS_RAW), ("Headless", HEADLESS_RAW), ("HTML-адаптеры", DATA_DIR / "html_adapters_collected_raw.json")]:
        data = load_json(path)
        if data:
            items = data["items"] if isinstance(data, dict) else data
            st.subheader(f"Последний результат — {label} ({len(items)})")
            if items:
                df = pd.DataFrame(items)
                cols_show = [c for c in ["source_id", "country", "title", "published", "in_window", "channel_priority"] if c in df.columns]
                st.dataframe(df[cols_show], width='stretch', height=300)

# --------------------------------------------------------------------------- Фильтр
elif page == "🔎 Фильтр":
    st.title("Тематический фильтр и дедупликация")
    st.caption("Отсеивает вакансии/рекламу, оставляет только отраслевые новости, убирает дубли по ссылке.")

    if st.button("▶️ Запустить фильтр", type="primary"):
        from ppi_radar.processing.filter import run_with_stats
        with st.spinner("Фильтрую..."):
            try:
                result, stats = run_with_stats()
                st.session_state["filter_stats"] = stats
                st.success(f"После фильтра: {len(result)} записей из {stats['total']} собранных")
            except Exception as e:
                st.error(f"Ошибка: {e}")

    stats = st.session_state.get("filter_stats")
    if stats:
        st.subheader("Воронка отсева — куда делись новости")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Собрано", stats["total"])
        c2.metric("Вне окна свежести", stats["dropped_outside_window"])
        c3.metric("Без заголовка", stats["dropped_no_title"])
        c4.metric("Дубли", stats["dropped_duplicate_link"])
        c5.metric("Не про ЦБП", stats["dropped_not_relevant"])
        window_hours_display = int(os.environ.get("PPI_RSS_WINDOW_HOURS", "168"))
        st.caption(
            f"Прошло: {stats['passed']} из {stats['total']}. Если основная масса отсеялась "
            f"«вне окна свежести» — это нормально: RSS-фиды отдают все свои записи, а не только "
            f"свежие, и большинство просто старше {window_hours_display // 24} дн. "
            f"Увеличьте окно на вкладке «🌐 Сбор», если хотите видеть больше. Если основная масса "
            f"отсеялась как «не про ЦБП» — источники в базе не отраслевые (общие СМИ/ведомства), "
            f"это тоже ожидаемо для источников без узкой специализации."
        )
        if stats.get("per_source"):
            st.subheader("Группировка по источникам — собрано / прошло")
            df_src = pd.DataFrame(stats["per_source"])
            st.dataframe(
                df_src[["source_id", "country", "collected", "passed", "outside_window", "not_relevant", "duplicate"]],
                width='stretch', height=400,
            )
            zero_passed = df_src[(df_src["collected"] > 0) & (df_src["passed"] == 0)]
            if len(zero_passed):
                st.caption(f"⚠️ {len(zero_passed)} источников собрали новости, но НИ ОДНА не прошла фильтр — "
                           f"посмотрите на причину (вне окна / не по теме) в таблице выше.")

    data = load_json(FILTERED)
    if data:
        st.subheader(f"Текущий результат ({len(data)} записей)")
        df = pd.DataFrame(data)
        if not df.empty:
            by_country = df["country"].value_counts()
            st.bar_chart(by_country)
            cols_show = [c for c in ["source_id", "country", "title", "link"] if c in df.columns]
            st.dataframe(df[cols_show], width='stretch', height=400)
    else:
        st.info("Сначала выполните шаг «🌐 Сбор».")

# --------------------------------------------------------------------------- Редактура
elif page == "🤖 Редактура":
    st.title("LLM-скоринг, перевод и отбор дневного дайджеста")
    st.caption("Формула из algoritm_main.md: global_score / russia_score + перевод + комментарии мир/Россия.")

    if not provider_ready():
        st.warning(f"LLM-провайдер '{LLM_PROVIDER}' не настроен — будет использована грубая "
                    f"эвристика вместо реальной редакторской оценки. Настройте бесплатный "
                    f"провайдер (Groq/Gemini/Ollama) на вкладке «⚙️ Настройки».")

    col1, col2, col3 = st.columns(3)
    with col1:
        per_country = st.slider("Новостей на страну БРИКС+ (кроме России)", min_value=1, max_value=5, value=1,
                                 help="Если после фильтра новостей мало, увеличьте — иначе в дайджест "
                                      "попадёт максимум по 1 на страну, даже если прошло больше.")
    with col2:
        russia_count = st.slider("Новостей по России отдельно", min_value=1, max_value=5, value=2,
                                  help="Россия традиционно получает больше внимания, чем другие "
                                       "страны БРИКС+ — отдельный счётчик, как в редакционном ТЗ.")
    with col3:
        max_world = st.slider("Мировых новостей (вне БРИКС+)", min_value=0, max_value=10, value=3)

    st.caption("Отбор идёт строгим каскадом по приоритету источника: сначала пробуем источники "
               "уровня **A**, и только если там для позиции ничего не нашлось — переходим к **B**, "
               "потом к **C**. Источники уровня **NO** продолжают собираться в общую базу, но никогда "
               "не участвуют в конкурсе за место в дайджесте. Приоритет задан в "
               "`sources/first_channel_priority.csv`.")

    if st.button("▶️ Оценить и отобрать дайджест", type="primary"):
        if not FILTERED.exists():
            st.error("Нет отфильтрованных данных — сначала выполните шаг «🔎 Фильтр».")
        else:
            from ppi_radar.processing.editor import score_items_with_warnings, select_daily_digest_with_reasoning
            filtered = load_json(FILTERED)
            progress_bar = st.progress(0.0, text="Начинаю оценку...")

            def _progress(batch_idx, num_batches):
                frac = batch_idx / num_batches if num_batches else 1.0
                progress_bar.progress(frac, text=f"Батч {batch_idx}/{num_batches} "
                                                   f"(если долго — вероятно, ждём лимит бесплатного тарифа)")

            try:
                scored, warnings = score_items_with_warnings(filtered, progress_callback=_progress)
                digest, reasoning = select_daily_digest_with_reasoning(
                    scored, BRICS_PLUS_COUNTRIES, per_country=per_country,
                    max_world=max_world, russia_count=russia_count)
                st.session_state["selection_reasoning"] = reasoning
                progress_bar.empty()
                st.success(f"В дневной дайджест отобрано: {len(digest)} карточек "
                           f"из {len(filtered)} прошедших фильтр")
                if warnings:
                    with st.expander(f"⚠️ Предупреждения ({len(warnings)}) — почему часть новостей "
                                      f"могла остаться без реальной оценки", expanded=True):
                        for w in warnings:
                            st.warning(w)
            except Exception as e:
                progress_bar.empty()
                st.error(f"Ошибка: {e}")

    reasoning = st.session_state.get("selection_reasoning")
    candidates = load_json(CANDIDATES)

    _TIER_ICON = {"A": "🟢", "B": "🟡", "C": "🟠", "NO": "⚫", "UNRANKED": "⚪"}

    def _render_candidate_row(c: dict, key: str) -> dict | None:
        """Рисует одну строку чек-листа: галочка + причина + саммари + кнопка полного просмотра.
        Возвращает кандидата, если он отмечен, иначе None."""
        col_check, col_more = st.columns([6, 1])
        with col_check:
            tier = c.get("channel_priority", "UNRANKED")
            tier_icon = _TIER_ICON.get(tier, "⚪")
            label = f"{tier_icon} [{tier}] [{c['global_score']}/{c['russia_score']}] {c['headline_ru'][:100]}"
            checked = st.checkbox(label, value=c.get("selected", False), key=key)
            icon = "✅" if c.get("selected") else "❌"
            st.caption(f"{icon} {c.get('reason', '')}")
            if c.get("summary_250"):
                st.caption(c["summary_250"])
        with col_more:
            with st.popover("📄 Подробнее"):
                st.markdown(f"**Заголовок:** {c.get('headline_ru', '')}")
                if c.get("summary_250"):
                    st.markdown(f"**Резюме:**\n\n{c['summary_250']}")
                st.markdown(f"🌍 **Мир:** {c.get('world_comment', '')}")
                st.markdown(f"🇷🇺 **Россия:** {c.get('russia_comment', '')}")
                st.divider()
                st.markdown(f"**Приоритет источника:** {tier_icon} {tier}")
                st.markdown("**Оригинал источника (как есть, до перевода):**")
                st.markdown(f"*{c.get('original_title', '(нет заголовка)')}*")
                if c.get("original_summary"):
                    st.caption(c["original_summary"])
                for src in c.get("sources", []):
                    if src:
                        st.link_button("🔗 Открыть источник", src)
        return c if checked else None

    if candidates:
        st.subheader("🔍 Почему выбраны именно эти новости — и правьте выбор здесь же")
        st.caption("Отмечено галочкой — то, что автоматика выбрала по умолчанию, с указанием причины "
                   "под каждой строкой. «📄 Подробнее» — полный текст источника (до перевода) и ссылка "
                   "на оригинал. Снимайте/ставьте галочки на ЛЮБЫЕ новости из пула (не только по своей "
                   "стране) — дайджест пересоберётся из того, что отмечено, когда нажмёте кнопку внизу.")

        checked_candidates = []

        st.markdown("### По странам БРИКС+")
        for country, country_candidates in candidates.get("by_country", {}).items():
            if country_candidates:
                st.markdown(f"**{country}** ({len(country_candidates)} кандидатов)")
                for idx, c in enumerate(country_candidates):
                    result = _render_candidate_row(c, key=f"cand_country_{country}_{idx}")
                    if result:
                        checked_candidates.append(result)
            else:
                st.markdown(f"**{country}** — нет новостей, прошедших фильтр в этом прогоне")

        world_by_country = candidates.get("world_by_country", {})
        if world_by_country:
            st.markdown("### Мир (вне БРИКС+) — по странам")
            for country, country_candidates in sorted(world_by_country.items(),
                                                        key=lambda kv: -max(c["global_score"] for c in kv[1])):
                st.markdown(f"**{country}** ({len(country_candidates)} кандидатов)")
                for idx, c in enumerate(country_candidates):
                    result = _render_candidate_row(c, key=f"cand_world_{country}_{idx}")
                    if result:
                        checked_candidates.append(result)

        st.caption(f"Отмечено к включению: {len(checked_candidates)}")

        if st.button("💾 Применить выбор и пересобрать дайджест", type="primary"):
            from ppi_radar.editorial_log import log_decisions
            all_flat = [c for lst in candidates.get("by_country", {}).values() for c in lst]
            all_flat += [c for lst in candidates.get("world_by_country", {}).values() for c in lst]
            checked_ids = {(c.get("source_id"), c.get("headline_ru")) for c in checked_candidates}
            for c in all_flat:
                c["selected"] = (c.get("source_id"), c.get("headline_ru")) in checked_ids
                c["reason"] = "выбрано вручную в чек-листе" if c["selected"] else "снята галочка вручную в чек-листе"
            log_decisions(all_flat, decision_source="manual_checklist")

            new_digest = {"items": [
                {
                    "country": c["country"],
                    "headline_ru": c["headline_ru"],
                    "summary_250": c.get("summary_250", ""),
                    "world_comment": c["world_comment"],
                    "russia_comment": c["russia_comment"],
                    "global_score": c["global_score"],
                    "russia_score": c["russia_score"],
                    "sources": c["sources"],
                    "channel_priority": c.get("channel_priority", "UNRANKED"),
                    "include": True,
                    "image_url": None,  # картинки нет у "новых" отмеченных — пересоберите на след. шаге
                }
                for c in checked_candidates
            ]}
            DIGEST.write_text(json.dumps(new_digest, ensure_ascii=False, indent=2), encoding="utf-8")
            st.success(f"Дайджест пересобран: {len(checked_candidates)} карточек. "
                       f"Если были картинки — пересоберите их на вкладке «🖼️ Картинки».")
            st.rerun()

    digest = load_json(DIGEST)
    if digest:
        st.divider()
        st.subheader(f"Текущий дайджест ({len(digest['items'])})")
        df = pd.DataFrame(digest["items"])
        cols_show = [c for c in ["country", "global_score", "russia_score", "headline_ru"] if c in df.columns]
        st.dataframe(df[cols_show], width='stretch', height=350)

        st.subheader("Полные карточки")
        for item in digest["items"]:
            with st.expander(f"{item.get('country')} — global {item.get('global_score')} / russia {item.get('russia_score')}"):
                st.write(f"**{item.get('headline_ru')}**")
                if item.get("summary_250"):
                    st.caption(item["summary_250"])
                st.write(f"🌍 Мир: {item.get('world_comment')}")
                st.write(f"🇷🇺 Россия: {item.get('russia_comment')}")
                st.write(f"Источники: {item.get('sources')}")
    else:
        st.info("Пока нет отобранного дайджеста.")

# --------------------------------------------------------------------------- Картинки
elif page == "🖼️ Картинки":
    st.title("Проверка og:image")
    st.caption("Правило: есть фото у источника → используем как превью; нет → публикуем без картинки.")

    if st.button("▶️ Найти картинки для отобранных карточек", type="primary"):
        if not DIGEST.exists():
            st.error("Сначала выполните шаг «🤖 Редактура».")
        else:
            from ppi_radar.processing.images import attach_images
            digest = load_json(DIGEST)
            with st.spinner("Проверяю og:image на источниках..."):
                try:
                    digest["items"] = attach_images(digest["items"])
                    DIGEST.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
                    found = sum(1 for i in digest["items"] if i.get("image_url"))
                    st.success(f"Картинки найдены для {found} из {len(digest['items'])} карточек")
                except Exception as e:
                    st.error(f"Ошибка: {e}")

    digest = load_json(DIGEST)
    if digest:
        for item in digest["items"]:
            col1, col2 = st.columns([1, 3])
            with col1:
                if item.get("image_url"):
                    st.image(item["image_url"], width=160)
                else:
                    st.caption("без картинки")
            with col2:
                st.write(f"**{item.get('country')}** — {item.get('headline_ru', '')[:120]}")

# --------------------------------------------------------------------------- Карточки и публикация
elif page == "📰 Карточки и публикация":
    st.title("Карточки и публикация в Telegram")

    digest = load_json(DIGEST)
    if not digest or not digest.get("items"):
        st.info("Сначала пройдите этапы «🤖 Редактура» (и по желанию «🖼️ Картинки»).")
        st.stop()

    st.subheader("1. Проверьте и отредактируйте карточки")
    st.caption("Текст можно поправить прямо здесь. Заменить новость на другую по стране можно "
               "раньше, на вкладке «🤖 Редактура». Снимите галочку у карточек, которые не хотите публиковать.")

    edited_items = []
    for i, item in enumerate(digest["items"]):
        include_default = item.get("include", True)
        header = f"{'✅' if include_default else '⬜'} {item.get('country')} — {item.get('headline_ru', '')[:70]}"
        with st.expander(header, expanded=False):
            include = st.checkbox("Включить в публикацию", value=include_default, key=f"include_{i}")
            headline = st.text_area("Заголовок (headline_ru)", value=item.get("headline_ru", ""),
                                     key=f"headline_{i}", height=80)
            world_c = st.text_area("Комментарий: Мир", value=item.get("world_comment", ""),
                                    key=f"world_{i}", height=80)
            russia_c = st.text_area("Комментарий: Россия", value=item.get("russia_comment", ""),
                                     key=f"russia_{i}", height=80)
            if item.get("image_url"):
                st.image(item["image_url"], width=200)
            st.caption(f"Оценки: global {item.get('global_score')} / russia {item.get('russia_score')} "
                       f"· Источники: {item.get('sources')}")

        edited = dict(item)
        edited.update({
            "include": include, "headline_ru": headline,
            "world_comment": world_c, "russia_comment": russia_c,
        })
        edited_items.append(edited)

    included_count = sum(1 for it in edited_items if it["include"])
    st.caption(f"Отмечено к публикации: {included_count} из {len(edited_items)}")

    if st.button("💾 Сохранить правки"):
        digest["items"] = edited_items
        DIGEST.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
        st.success("Правки сохранены.")

    st.divider()
    st.subheader("2. Соберите карточки")
    issue_date = st.text_input("Дата выпуска", value=date.today().strftime("%d.%m.%Y"))

    if st.button("▶️ Собрать карточки (только отмеченные)", type="primary"):
        from ppi_radar.publishing.cards import build_cards, save_cards
        digest_for_cards = {"items": [it for it in edited_items if it["include"]]}
        if not digest_for_cards["items"]:
            st.error("Нет ни одной отмеченной карточки — нечего собирать.")
        else:
            cards = build_cards(digest_for_cards, issue_date=issue_date)
            save_cards(cards)
            st.session_state["cards"] = cards
            st.success(f"Собрано {len(cards)} карточек (из {included_count} отмеченных + intro)")

    cards = st.session_state.get("cards")

    if cards:
        st.divider()
        st.subheader("3. Предпросмотр")
        for name, text, image_url in cards:
            with st.container(border=True):
                if image_url:
                    st.image(image_url, width=200)
                st.markdown(text.replace("\n", "  \n"), unsafe_allow_html=False)
                st.caption(f"{len(text)} символов" + (" — ⚠️ превышает лимит Telegram (4096)" if len(text) > 4096 else ""))

        st.divider()
        st.subheader("4. Публикация")
        if not TELEGRAM_BOT_TOKEN:
            st.error("TELEGRAM_BOT_TOKEN не задан — публикация недоступна. Задайте его в «⚙️ Настройки».")
        else:
            confirm = st.checkbox("Я проверил карточки выше и готов опубликовать их в канал @PPIGlobalRadar")
            if st.button("🚀 Опубликовать в Telegram", disabled=not confirm, type="primary"):
                from ppi_radar.publishing.telegram import publish_cards
                with st.spinner("Публикую..."):
                    try:
                        publish_cards(cards, dry_run=False)
                        st.success("Отправлено в канал.")
                    except Exception as e:
                        st.error(f"Ошибка публикации: {e}")
    else:
        st.info("Соберите карточки кнопкой выше, чтобы увидеть предпросмотр и опубликовать.")

# --------------------------------------------------------------------------- Источники
elif page == "🔬 Источники":
    st.title("Расширение охвата источников")

    from ppi_radar.collectors.discover_rss import load_discovered

    cov = sources_mod.coverage_summary()
    all_rows = sources_mod.load_sources()
    discovery_rows = [r for r in all_rows if r.get("endpoint_status", "").strip() == "DISCOVERY_REQUIRED"]
    rss_candidate_rows = [r for r in discovery_rows if "RSS" in r.get("fetch_method", "")]
    priority_a_rows = [r for r in discovery_rows if r.get("editorial_priority", "").strip() == "A"]
    already = load_discovered()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Рабочих в официальной базе", cov["working"])
    c2.metric("Автонайдено дополнительно", len(already))
    c3.metric("Непроверенных", cov["discovery_required"])
    c4.metric("Заблокировано/мертво", cov["blocked_or_dead"])

    st.caption(
        f"Автопоиск проверяет непроверенные источники, у которых в базе указано, что они "
        f"могут отдавать RSS (сейчас это {len(rss_candidate_rows)} из {cov['discovery_required']} "
        f"непроверенных), и ищет реальный адрес фида через стандартный механизм "
        f"автообнаружения (`<link rel=\"alternate\">` в HTML главной страницы) — так делает "
        f"любой RSS-ридер. Кандидат засчитывается только если фид реально парсится и "
        f"содержит записи. Найденные источники сохраняются отдельно от официальной базы v9 "
        f"и не портят её — они просто добавляются к рабочим RSS-источникам "
        f"(сейчас их уже {len(already)}, включая источники из других загруженных вами баз)."
    )

    if st.button("🔍 Найти новые RSS-источники", type="primary"):
        from ppi_radar.collectors.discover_rss import discover_candidates
        progress = st.progress(0.0, text="Проверяю источники...")
        log_box = st.empty()

        def _cb(i, total, row):
            progress.progress((i + 1) / total, text=f"{i+1}/{total}: {row.get('source_id')} ({row.get('country')})")

        with st.spinner(f"Проверяю до {len(rss_candidate_rows)} источников — это может занять пару минут..."):
            found = discover_candidates(progress_callback=_cb)
        progress.empty()
        st.session_state["discovered_candidates"] = found
        st.success(f"Найдено рабочих фидов: {len(found)}")

    found = st.session_state.get("discovered_candidates")
    if found:
        st.subheader(f"Найденные кандидаты ({len(found)})")
        df = pd.DataFrame(found)
        st.dataframe(df[["source_id", "country", "org", "rss_url", "entry_count"]],
                     width='stretch', height=300)

        if st.button("➕ Добавить все найденные в рабочую базу", type="primary"):
            from ppi_radar.collectors.discover_rss import save_discovered
            save_discovered(found)
            st.success(f"Добавлено {len(found)} источников. Теперь они будут учитываться на шаге «🌐 Сбор».")
            st.session_state.pop("discovered_candidates", None)

    if already:
        st.divider()
        st.subheader(f"Уже добавленные ранее источники ({len(already)})")
        st.dataframe(pd.DataFrame(already)[["source_id", "country", "org", "rss_url", "entry_count"]],
                     width='stretch', height=200)

    st.divider()
    non_rss_discovery = len(discovery_rows) - len(rss_candidate_rows)
    st.caption(
        f"Остальные ~{non_rss_discovery} непроверенных источников (без указания RSS в базе) "
        f"требуют ручной разведки — у каждого сайта своя вёрстка/защита, это нельзя "
        f"автоматизировать вслепую. Приоритет — {len(priority_a_rows)} источников с "
        f"editorial_priority=A среди непроверенных (см. таблицу на вкладке «⚙️ Настройки»)."
    )

# --------------------------------------------------------------------------- Настройки
elif page == "⚙️ Настройки":
    st.title("Настройки")

    st.subheader("Telegram")
    tg_token_input = st.text_input("TELEGRAM_BOT_TOKEN", value=TELEGRAM_BOT_TOKEN, type="password",
                                    help="@BotFather → /mybots → @PPIRadar1_bot → API Token")
    tg_chat_input = st.text_input("TELEGRAM_CHAT_ID", value=TELEGRAM_CHAT_ID)

    st.subheader("LLM для редакторского шага (скоринг/перевод/комментарии)")
    st.caption("groq, gemini и openrouter — бесплатно (у каждого свой free tier с лимитами). "
               "ollama — бесплатно и локально (нужен установленный Ollama). anthropic — платно. "
               "Заполните ключи для нескольких провайдеров и настройте порядок автопереключения "
               "ниже — если у первого кончится лимит, редактор сам перейдёт к следующему.")

    from ppi_radar.config import (
        CEREBRAS_API_KEY, CEREBRAS_MODEL, GEMINI_API_KEY, GEMINI_MODEL,
        GROQ_API_KEY, GROQ_MODEL, LLM_PROVIDER, LLM_PROVIDER_CHAIN,
        MISTRAL_API_KEY, MISTRAL_MODEL, OLLAMA_BASE_URL, OLLAMA_MODEL,
        OPENROUTER_API_KEY, OPENROUTER_MODEL,
    )

    st.markdown("**Автопереключение (необязательно)**")
    st.caption("Задайте порядок опроса провайдеров. Пропустите ненужные позиции — "
               "«не использовать». Если оставить всё пустым, будет применяться только "
               "одиночный LLM_PROVIDER ниже, без автопереключения.")
    ALL_PROVIDERS = ["— не использовать —", "groq", "cerebras", "mistral", "gemini",
                      "openrouter", "ollama", "anthropic"]
    existing_chain = [p.strip() for p in LLM_PROVIDER_CHAIN.split(",") if p.strip()]
    chain_slots = []
    cols = st.columns(4)
    for slot in range(4):
        default_val = existing_chain[slot] if slot < len(existing_chain) else "— не использовать —"
        with cols[slot]:
            choice = st.selectbox(f"{slot + 1}-й приоритет", ALL_PROVIDERS,
                                   index=ALL_PROVIDERS.index(default_val) if default_val in ALL_PROVIDERS else 0,
                                   key=f"chain_slot_{slot}")
            if choice != "— не использовать —":
                chain_slots.append(choice)

    st.divider()
    st.markdown("**Одиночный провайдер (используется, если цепочка выше пустая)**")
    _SINGLE_PROVIDERS = ["groq", "cerebras", "mistral", "gemini", "openrouter", "ollama", "anthropic"]
    provider_input = st.selectbox(
        "LLM_PROVIDER", _SINGLE_PROVIDERS,
        index=_SINGLE_PROVIDERS.index(LLM_PROVIDER) if LLM_PROVIDER in _SINGLE_PROVIDERS else 0,
    )

    st.divider()
    st.markdown("**Ключи и модели по каждому провайдеру** (заполните все, которые собираетесь использовать)")

    st.markdown("Groq — бесплатный ключ: https://console.groq.com/keys")
    st.caption("Groq периодически меняет список разрешённых моделей на бесплатном тарифе — "
               "точный список для вашего аккаунта: https://console.groq.com/settings/limits")
    groq_key_input = st.text_input("GROQ_API_KEY", value=GROQ_API_KEY, type="password", key="groq_key")
    groq_model_input = st.text_input("GROQ_MODEL", value=GROQ_MODEL, key="groq_model")

    st.markdown("Cerebras — бесплатный ключ: https://cloud.cerebras.ai (раздел API Keys, начинается с `csk-`)")
    st.caption("30 запросов/мин, 14 400/день — та же щедрость, что у Groq, работает на "
               "собственном железе Cerebras, реально быстро.")
    cerebras_key_input = st.text_input("CEREBRAS_API_KEY", value=CEREBRAS_API_KEY, type="password", key="cerebras_key")
    cerebras_model_input = st.text_input("CEREBRAS_MODEL", value=CEREBRAS_MODEL, key="cerebras_model")

    st.markdown("Mistral AI — бесплатный ключ: https://console.mistral.ai (раздел API Keys)")
    st.caption("Лимит считается за МЕСЯЦ (1 млрд токенов/мес), а не за день — самый большой "
               "совокупный запас среди всех провайдеров здесь. Хорош как последний в цепочке.")
    mistral_key_input = st.text_input("MISTRAL_API_KEY", value=MISTRAL_API_KEY, type="password", key="mistral_key")
    mistral_model_input = st.text_input("MISTRAL_MODEL", value=MISTRAL_MODEL, key="mistral_model")

    st.markdown("Gemini — бесплатный ключ: https://aistudio.google.com/apikey")
    st.caption("⚠️ Из России Gemini API часто отдаёт ошибку «429 quota exceeded» даже когда в "
               "кабинете AI Studio лимиты показывают 0/пусто — это, скорее всего, не реальная "
               "квота, а региональная недоступность (Google сократил присутствие в РФ с 2022 "
               "года). Держите Gemini не первым в цепочке автопереключения, если сталкиваетесь "
               "с этим постоянно.")
    gemini_key_input = st.text_input("GEMINI_API_KEY", value=GEMINI_API_KEY, type="password", key="gemini_key")
    gemini_model_input = st.text_input("GEMINI_MODEL", value=GEMINI_MODEL, key="gemini_model")

    st.markdown("OpenRouter — бесплатный ключ: https://openrouter.ai/keys (карта не нужна для моделей "
                "с суффиксом :free). ⚠️ Бесплатного DeepSeek там больше нет — модель по умолчанию "
                "`openrouter/free` сама выбирает доступную бесплатную модель (Llama/Qwen/GPT-OSS и т.п.).")
    openrouter_key_input = st.text_input("OPENROUTER_API_KEY", value=OPENROUTER_API_KEY, type="password",
                                          key="openrouter_key")
    openrouter_model_input = st.text_input("OPENROUTER_MODEL", value=OPENROUTER_MODEL, key="openrouter_model")

    st.markdown("Ollama — локально и бесплатно: установите https://ollama.com, затем "
                "`ollama pull llama3.1`, и убедитесь что `ollama serve` запущен.")
    ollama_url_input = st.text_input("OLLAMA_BASE_URL", value=OLLAMA_BASE_URL, key="ollama_url")
    ollama_model_input = st.text_input("OLLAMA_MODEL", value=OLLAMA_MODEL, key="ollama_model")

    st.markdown("Anthropic — платный API: https://console.anthropic.com/")
    anthropic_input = st.text_input("ANTHROPIC_API_KEY", value=ANTHROPIC_API_KEY, type="password",
                                     key="anthropic_key")

    if st.button("💾 Сохранить настройки", type="primary"):
        save_env_value("TELEGRAM_BOT_TOKEN", tg_token_input)
        save_env_value("TELEGRAM_CHAT_ID", tg_chat_input)
        save_env_value("LLM_PROVIDER", provider_input)
        save_env_value("LLM_PROVIDER_CHAIN", ",".join(chain_slots))
        save_env_value("GROQ_API_KEY", groq_key_input)
        save_env_value("GROQ_MODEL", groq_model_input)
        save_env_value("CEREBRAS_API_KEY", cerebras_key_input)
        save_env_value("CEREBRAS_MODEL", cerebras_model_input)
        save_env_value("MISTRAL_API_KEY", mistral_key_input)
        save_env_value("MISTRAL_MODEL", mistral_model_input)
        save_env_value("GEMINI_API_KEY", gemini_key_input)
        save_env_value("GEMINI_MODEL", gemini_model_input)
        save_env_value("OPENROUTER_API_KEY", openrouter_key_input)
        save_env_value("OPENROUTER_MODEL", openrouter_model_input)
        save_env_value("OLLAMA_BASE_URL", ollama_url_input)
        save_env_value("OLLAMA_MODEL", ollama_model_input)
        save_env_value("ANTHROPIC_API_KEY", anthropic_input)
        cfg.reload_env()
        st.success("Сохранено в .env и применено сразу (без перезапуска).")

    st.divider()
    st.subheader("База источников")
    st.caption(f"Файл: `{sources_mod.SOURCES_CSV}`")
    rows = sources_mod.load_sources()
    df = pd.DataFrame(rows)
    if not df.empty:
        status_filter = st.multiselect("Фильтр по статусу", sorted(df["endpoint_status"].unique()),
                                        default=[])
        show_df = df[df["endpoint_status"].isin(status_filter)] if status_filter else df
        st.dataframe(show_df, width='stretch', height=400)
