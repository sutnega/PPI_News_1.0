"""
LLM-редактор — автоматизация редакторской оценки важности, перевода,
резюме и комментария "мир/Россия" + строгий каскадный отбор источников
A→B→C (см. TZ_PPI_Radar_AI_pipeline, раздел 8).

Формула скоринга (раздел "Базовая формула"):
    итоговая важность = 25% масштаб воздействия
                       + 15% влияние на производственные мощности
                       + 15% влияние на международную торговлю
                       + 10% технологическая новизна
                       + 10% регуляторные последствия
                       + 10% экологическое значение
                       (+ оставшиеся 15% — по усмотрению модели, компоненты
                       не обязаны суммироваться строго до 100%, это
                       ориентир для LLM-суждения)
считается дважды — как global_score и как russia_score (второй отвечает
на вопрос "может ли это повлиять на российский рынок/экспорт/импорт/
технологии/оборудование/цены/регулирование").

Без ключа выбранного провайдера этот шаг работать не будет — тогда пайплайн
использует правило по умолчанию (см. _fallback_score) и явно предупреждает,
что оценка не редакторская, а грубая эвристика.

Провайдер выбирается через LLM_PROVIDER в .env: groq/gemini/openrouter
(бесплатно), ollama (бесплатно, локально), anthropic (платно).
Можно задать цепочку автопереключения через LLM_PROVIDER_CHAIN
("groq,gemini,openrouter") — если у первого кончился лимит, редактор
автоматически пробует следующего. См. .env.example.

Отбор в дайджест — строгий каскад A→B→C→UNRANKED по приоритету источника
(см. source_priority.py): каждая позиция (страна/Россия/мир) сначала ищет
кандидата среди источников уровня A; если там пусто — переходит к B; если
и там пусто — к C; если и там пусто — к ещё не проранжированным. Уровни не
смешиваются: наличие хоть одного кандидата A полностью закрывает позицию
для B и C, даже если там формально более сильная по очкам новость.
"""
from __future__ import annotations

import json
import re
import time

from .. import config as cfg
from ..config import DATA_DIR
from ..editorial_log import log_decisions
from ..error_log import log_error
from .llm_providers import call_llm_with_fallback, get_last_rate_limit, get_provider_chain, parse_reset_duration

_PROVIDER_HAS_KEY = {
    "groq": lambda: bool(cfg.GROQ_API_KEY),
    "gemini": lambda: bool(cfg.GEMINI_API_KEY),
    "anthropic": lambda: bool(cfg.ANTHROPIC_API_KEY),
    "openrouter": lambda: bool(cfg.OPENROUTER_API_KEY),
    "cerebras": lambda: bool(cfg.CEREBRAS_API_KEY),
    "mistral": lambda: bool(cfg.MISTRAL_API_KEY),
    "ollama": lambda: True,  # ключ не нужен, но сервер может быть недоступен — проверяется при вызове
}

SCORED_OUTPUT = DATA_DIR / "scored.json"
DIGEST_OUTPUT = DATA_DIR / "digest_cards.json"
CANDIDATES_OUTPUT = DATA_DIR / "candidates_by_country.json"

BATCH_SIZE = 4  # уменьшено с 8: Groq считает TPM как (входные_токены + max_tokens), то есть
                 # ЗАРЕЗЕРВИРОВАННЫЙ потолок, а не реально сгенерированное — при BATCH_SIZE=8 и
                 # max_tokens=6000 один запрос уже сам по себе вплотную подходил к лимиту 8000
                 # TPM (openai/gpt-oss-120b на Groq), отсюда HTTP 413 и обрыв JSON. См. _max_tokens_for_batch.

# Грубая оценка токенов на одну новость в ответе — с запасом, потому что
# кириллица у большинства токенизаторов "дороже" латиницы (больше токенов
# на тот же текст), а промпт требует headline+summary_250+два развёрнутых
# комментария на новость.
_TOKENS_PER_ITEM_ESTIMATE = 650  # поднято с 550: после перебалансировки summary_250 стал длиннее
                                   # (400-450 знаков вместо 250), хотя world/russia_comment короче
_PROMPT_OVERHEAD_ESTIMATE = 1200  # системный промпт + входные данные батча


def _max_tokens_for_batch(batch_size: int, ceiling: int = 6000) -> int:
    """
    Запас на ответ под конкретный размер батча — не фиксированная константа.
    Считается так, чтобы (промпт + вход + это значение) оставалось заметно
    ниже типичного TPM-лимита бесплатных тарифов (у Groq на некоторых
    моделях всего 8000 токенов/минуту, и это НЕ реально сгенерированное,
    а именно зарезервированное — см. документацию Groq по rate limits).
    """
    return min(ceiling, _PROMPT_OVERHEAD_ESTIMATE + _TOKENS_PER_ITEM_ESTIMATE * batch_size)


SYSTEM_PROMPT = """Ты — редактор отраслевого дайджеста PPI Global Radar о целлюлозно-бумажной \
промышленности (ЦБП) и упаковке. Тебе присылают JSON-массив новостных карточек (на языке \
оригинала). Для КАЖДОЙ карточки верни оценку и редакторские материалы на русском языке.

Формула важности (ориентир, не обязана суммироваться в 100 строго):
25% масштаб воздействия на отрасль + 15% влияние на производственные мощности +
15% влияние на международную торговлю + 10% технологическая новизна +
10% регуляторные последствия + 10% экологическое значение + остальное — общая значимость события.

Для каждой карточки посчитай ДВЕ оценки 0-100:
- global_score — насколько событие важно для мировой ЦБП
- russia_score — может ли оно повлиять на российский рынок, экспорт, импорт, технологии, \
оборудование, цены или регулирование (если связи нет вообще — ставь низкий балл, не выдумывай её)

И подготовь СТРОГО четыре текстовых поля:

1. headline — короткий факт-ориентированный заголовок на русском (как настоящий заголовок новости,
   БЕЗ художественности), до 100 знаков.

2. summary_250 — резюме содержания новости на русском, В ПРЕДЕЛАХ 400-450 знаков. Это должен быть
   пересказ СУТИ статьи своими словами: что произошло, кто участник, какие цифры/даты названы —
   а не повтор заголовка другими словами. Это основной текст карточки — не экономь на нём.

3. world_comment — короткий, но конкретный анализ на 1-2 предложения, почему это важно для мировой
   отрасли. Требования к глубине при этой краткости (это не общие слова "это важно, потому что..."):
   - назови КОНКРЕТНЫЙ механизм влияния (не "влияет на рынок", а на ЧТО именно: объём предложения
     конкретного вида продукции, цена конкретного сырья, доля конкретного экспортёра/импортёра,
     конкретный регуляторный прецедент и т.п.)
   - если в новости есть цифры, компании, объёмы, даты — используй их, не повторяй summary_250
   - если событие рядовое и реально не имеет значимых последствий — прямо напиши это одной фразой
     ("локальное событие без значимых последствий для отрасли в целом"), а не общей фразой-заглушкой

4. russia_comment — тот же принцип (конкретно, но коротко — 1-2 предложения) про связь с Россией.
   НЕ пиши сразу "прямых связей не создаёт" — сначала активно поищи КОНКРЕТНУЮ косвенную связь: как
   именно это влияет на мировые цены на сырьё/продукцию, которые затрагивают российских экспортёров/
   импортёров (назови КАКИХ, если можешь предположить по отрасли); создаёт ли прецедент регулирования,
   который могут перенять в РФ; меняет ли конкурентную позицию российских поставщиков на этом рынке;
   затрагивает ли технологии/оборудование, которое используется и в России. Пиши "прямых и косвенных
   связей с российским рынком не прослеживается" ТОЛЬКО если действительно перебрал эти варианты и
   связи нет — это должно быть редким, а не дефолтным ответом.

Верни СТРОГО JSON-массив (тот же порядок и длина, что во входном массиве), без markdown-обрамления, \
без пояснений до/после. Формат каждого элемента:
{"global_score": int, "russia_score": int, "headline": str, "summary_250": str, \
"world_comment": str, "russia_comment": str}
"""


def provider_ready() -> bool:
    """Настроен ли хотя бы один провайдер из цепочки (есть ключ / доступен локально)."""
    try:
        chain = get_provider_chain()
    except ValueError:
        return False
    return any(_PROVIDER_HAS_KEY.get(p, lambda: False)() for p in chain)


def _fallback_score(item: dict) -> dict:
    """Грубая эвристика на случай отсутствия API-ключа — НЕ замена редактуре."""
    text = f"{item.get('title','')} {item.get('summary','')}"
    length_bonus = min(len(text) // 20, 30)
    return {
        "global_score": 40 + length_bonus,
        "russia_score": 20,
        "headline": item.get("title", "")[:100],
        "summary_250": (item.get("summary", "") or item.get("title", ""))[:250],
        "world_comment": "Оценка не проводилась (LLM-провайдер не настроен) — требуется ручная редактура.",
        "russia_comment": "Оценка не проводилась (LLM-провайдер не настроен) — требуется ручная редактура.",
    }


def _call_llm_editor(batch: list[dict]) -> tuple[list[dict], str, list[str]]:
    """Возвращает (распарсенный_результат, использованный_провайдер, ошибки_остальных_в_цепочке)."""
    user_payload = json.dumps(
        [{"title": it.get("title"), "summary": it.get("summary"), "country": it.get("country")} for it in batch],
        ensure_ascii=False,
    )
    max_tokens = _max_tokens_for_batch(len(batch))
    text, used_provider, chain_errors = call_llm_with_fallback(SYSTEM_PROMPT, user_payload, max_tokens=max_tokens)
    if not text:
        # Провайдер ответил 200 OK, но content пустой/None — это НЕ проблема
        # лимитов/ключей (запрос дошёл и был принят), а скорее всего модель
        # не уложилась в max_tokens при таком размере батча и развёрнутом
        # промпте. Пишем честную причину, а не путаем с "цепочка недоступна".
        raise RuntimeError(
            f"'{used_provider}' вернул пустой ответ (content пустой/None) при HTTP 200 — "
            f"похоже, модель не уложилась в лимит токенов на этот батч (BATCH_SIZE={BATCH_SIZE}, "
            f"max_tokens={max_tokens}). Не лимит запросов и не проблема с ключом — это отдельная причина."
        )
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    if not text:
        raise RuntimeError(f"'{used_provider}' вернул ответ, состоящий только из markdown-обрамления "
                            f"без содержимого — так же похоже на обрезку по лимиту токенов.")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"'{used_provider}' вернул невалидный JSON ({e}) — вероятно, ответ обрезан "
                            f"по max_tokens посреди генерации (не лимит запросов, не ключ). "
                            f"Начало ответа: {text[:150]!r}") from e
    if len(parsed) != len(batch):
        raise ValueError(f"LLM вернул {len(parsed)} записей вместо {len(batch)}")
    return parsed, used_provider, chain_errors


def score_items(items: list[dict]) -> list[dict]:
    scored, _ = score_items_with_warnings(items)
    return scored


def score_items_with_warnings(items: list[dict], batch_delay_seconds: float = 2.0,
                               progress_callback=None) -> tuple[list[dict], list[str]]:
    """
    То же, что score_items(), но дополнительно возвращает список
    человекочитаемых предупреждений (например, про откат на эвристику
    из-за лимитов бесплатного тарифа, или про автопереключение на
    следующего провайдера в цепочке) — чтобы UI мог их показать, а не
    только консоль. progress_callback(batch_idx, num_batches), если
    передан, вызывается перед обработкой каждого батча — чтобы UI мог
    показать прогресс-бар вместо "зависшего" спиннера без обратной связи.
    """
    try:
        chain = get_provider_chain()
    except ValueError as e:
        chain = []
        print(f"ВНИМАНИЕ: {e}")

    use_llm = any(_PROVIDER_HAS_KEY.get(p, lambda: False)() for p in chain)

    warnings: list[str] = []
    if not use_llm:
        msg = (f"Ни один провайдер из цепочки {chain or [cfg.LLM_PROVIDER]} не настроен (нет ключа) — "
               f"используется грубая эвристика, не настоящая редакторская оценка.")
        print(f"ВНИМАНИЕ: {msg}")
        warnings.append(msg)

    last_used_provider = None
    current_delay = batch_delay_seconds
    MAX_DELAY = 65.0  # было 30 — TPM-окно у бесплатных тарифов (Groq и т.п.) обычно 60с,
                       # с потолком в 30с реактивная пауза никогда не давала лимиту реально
                       # восстановиться при длинных прогонах (много батчей подряд)
    scored = []
    num_batches = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_idx, i in enumerate(range(0, len(items), BATCH_SIZE)):
        if progress_callback:
            progress_callback(batch_idx, num_batches)
        batch = items[i:i + BATCH_SIZE]

        # Проактивная пауза: смотрим остаток токенов ПЕРЕД отправкой, а не
        # только реагируем постфактум на 429. Если по последнему ответу
        # видно, что токенов может не хватить на следующий батч — ждём
        # ровно столько, сколько сервер сам сказал (x-ratelimit-reset-tokens),
        # а не гадаем с фиксированным шагом.
        if use_llm and last_used_provider:
            rl = get_last_rate_limit(last_used_provider)
            if rl:
                remaining = rl.get("x-ratelimit-remaining-tokens")
                needed = _max_tokens_for_batch(len(batch))
                if remaining is not None and int(remaining) < needed:
                    reset_wait = parse_reset_duration(rl.get("x-ratelimit-reset-tokens"))
                    wait = min(reset_wait, MAX_DELAY) if reset_wait else MAX_DELAY
                    print(f"  [{last_used_provider}] проактивно жду {wait:.0f}с — остаток токенов "
                          f"({remaining}) меньше нужного на следующий батч (~{needed})")
                    time.sleep(wait)

        batch_had_rate_limit = False
        try:
            if use_llm:
                results, used_provider, chain_errors = _call_llm_editor(batch)
                if chain_errors:
                    batch_had_rate_limit = True
                    warnings.append(f"Батч {i}-{i+len(batch)}: провайдер(ы) "
                                     f"{[e.split(':')[0] for e in chain_errors]} недоступны "
                                     f"({'; '.join(chain_errors)}), автопереключение на "
                                     f"'{used_provider}' сработало.")
                if used_provider != last_used_provider:
                    print(f"  используется провайдер: {used_provider}")
                last_used_provider = used_provider
            else:
                results = [_fallback_score(it) for it in batch]
        except ValueError as e:
            # len(parsed) != len(batch) — модель вернула валидный JSON, но с
            # неверным числом элементов (почти влезла в лимит, но не совсем).
            # Отдельная классификация — не то же самое, что пустой ответ или
            # битый JSON, диагностировать нужно иначе (обычно достаточно ещё
            # чуть уменьшить BATCH_SIZE).
            batch_had_rate_limit = True
            msg = f"Батч {i}-{i+len(batch)}: {e} — откат на эвристику для этих новостей."
            print(f"ERROR редактор: {msg}")
            warnings.append(msg)
            log_error("llm_editor", "item_count_mismatch", str(e), chain=str(chain),
                      batch_range=f"{i}-{i+len(batch)}")
            results = [_fallback_score(it) for it in batch]
        except Exception as e:
            batch_had_rate_limit = True
            msg = f"Батч {i}-{i+len(batch)}: {e} — откат на эвристику для этих новостей."
            print(f"ERROR редактор: {msg}")
            warnings.append(msg)
            log_error("llm_editor", "batch_failed", str(e), chain=str(chain),
                      batch_range=f"{i}-{i+len(batch)}")
            results = [_fallback_score(it) for it in batch]

        for it, res in zip(batch, results):
            merged = dict(it)
            merged.update(res)
            merged["sources"] = [it.get("link")] if it.get("link") else []
            scored.append(merged)

        # Адаптивная пауза между батчами: если в батче словили лимит хотя бы
        # у одного провайдера — увеличиваем паузу (у бесплатных тарифов
        # разные RPM: то, что нормально для Groq, может быть слишком часто
        # для Gemini). Если несколько батчей подряд прошли чисто — постепенно
        # снижаем обратно к базовому значению.
        if use_llm and batch_idx < num_batches - 1:
            if batch_had_rate_limit:
                current_delay = min(current_delay * 2, MAX_DELAY)
                print(f"  лимит на этом батче — увеличиваю паузу до {current_delay:.0f}с")
            else:
                current_delay = max(current_delay * 0.7, batch_delay_seconds)
            time.sleep(current_delay)

    if progress_callback:
        progress_callback(num_batches, num_batches)

    SCORED_OUTPUT.write_text(json.dumps(scored, ensure_ascii=False, indent=2), encoding="utf-8")
    return scored, warnings


def select_daily_digest(scored: list[dict], brics_countries: list[str],
                         max_world: int = 3, per_country: int = 1, russia_count: int = 2) -> list[dict]:
    """Обратная совместимость: только сами карточки, без reasoning."""
    items, _ = select_daily_digest_with_reasoning(scored, brics_countries, max_world, per_country, russia_count)
    return items


def _candidate_view(c: dict, country: str, selected: bool, reason: str) -> dict:
    """Единое представление кандидата — используется и для чек-листа в UI, и
    для итогового дайджеста. headline/summary_250/world_comment/russia_comment —
    то, что подготовил редактор; original_title/original_summary/link — то, что
    реально было в источнике, для проверки "а что там было на самом деле".
    headline_ru оставлен как алиас headline — для обратной совместимости с
    местами в UI/публикации, которые ещё читают старое имя поля."""
    headline = c.get("headline", c.get("headline_ru", c.get("title", "")))
    return {
        "headline": headline,
        "headline_ru": headline,
        "summary_250": c.get("summary_250", c.get("summary", "")),
        "world_comment": c.get("world_comment", ""),
        "russia_comment": c.get("russia_comment", ""),
        "global_score": c.get("global_score", 0),
        "russia_score": c.get("russia_score", 0),
        "sources": c.get("sources", []),
        "country": country,
        "selected": selected,
        "reason": reason,
        "original_title": c.get("title", ""),
        "original_summary": c.get("summary", ""),
        "source_id": c.get("source_id", ""),
        "channel_priority": c.get("channel_priority", "UNRANKED"),
    }


def _cascade_tier_and_pool(candidates: list[dict]) -> tuple[str | None, list[dict]]:
    """
    Строгий каскад A → B → C → UNRANKED: возвращает (уровень-победитель,
    кандидаты именно этого уровня). Уровни НЕ смешиваются — если в A есть
    хоть один кандидат, B и C не участвуют вообще, даже если там формально
    более сильная по очкам новость. Источники уровня NO сюда не передаются
    вообще — см. вызывающий код.
    """
    by_tier: dict[str, list[dict]] = {}
    for c in candidates:
        by_tier.setdefault(c.get("channel_priority", "UNRANKED"), []).append(c)
    for tier in ("A", "B", "C", "UNRANKED"):
        pool = by_tier.get(tier, [])
        if pool:
            return tier, pool
    return None, []


def _rank_with_cascade(country_scored: list[dict], count: int) -> list[dict]:
    """
    Отбирает до `count` кандидатов для одной позиции (страна/Россия/мир),
    строго по каскаду A→B→C→UNRANKED, и внутри выигравшего уровня — по
    сумме global_score+russia_score.
    """
    ranked = [c for c in country_scored if c.get("channel_priority") != "NO"]
    tier, pool = _cascade_tier_and_pool(ranked)
    if not pool:
        return []
    pool = sorted(pool, key=lambda x: x.get("global_score", 0) + x.get("russia_score", 0), reverse=True)
    return pool[:count]


def _reason_for(c: dict, winning_tier: str | None, picked: list[dict], count: int) -> str:
    tier = c.get("channel_priority", "UNRANKED")
    if c in picked:
        return f"выбрано — уровень источника {tier}"
    if tier == "NO":
        return "источник уровня NO — не участвует в ranking (продолжает собираться в общую базу)"
    if winning_tier and tier != winning_tier:
        order = ("A", "B", "C", "UNRANKED")
        if order.index(tier) > order.index(winning_tier):
            return (f"каскад остановился на уровне {winning_tier} (там нашёлся кандидат) — "
                    f"уровень {tier} не участвовал в конкурсе")
    return f"ниже по очкам в пределах своего уровня — прошло только {count} лучших на позицию"


def select_daily_digest_with_reasoning(scored: list[dict], brics_countries: list[str],
                                        max_world: int = 3, per_country: int = 1, russia_count: int = 2
                                        ) -> tuple[list[dict], dict]:
    """
    Отбор по каскаду A→B→C→UNRANKED источников (TZ_PPI_Radar_AI_pipeline,
    раздел 8): для каждой позиции сначала пробуем источники уровня A; если
    там подходящих новостей нет вообще — переходим к B; если и там пусто —
    к C; если и там пусто — к ранее не проранжированным (UNRANKED).
    Источники уровня NO из конкурса исключены совсем (но продолжают
    собираться в общую базу — см. archive.py).

    Позиции: по per_country новостей на каждую страну БРИКС+ (кроме
    России), russia_count новостей по России отдельно (обычно больше, чем
    по другим странам — это отдельный приоритет редакции), и до max_world
    новостей по остальному миру, из разных стран, тем же каскадом.

    Кандидаты (и для БРИКС+, и для "мира") сохраняются в единой структуре
    с пометкой selected/reason прямо в каждой записи. by_country включает
    ВСЕ страны из brics_countries, даже если кандидатов ноль.
    world_by_country группирует не-БРИКС+ новости по странам.
    """
    selected = []
    candidates_by_country: dict[str, list[dict]] = {}
    countries_without_candidates = []

    for country in brics_countries:
        country_scored = [s for s in scored if s.get("country") == country]
        count = russia_count if country == "Россия" else per_country
        picked = _rank_with_cascade(country_scored, count)
        winning_tier = picked[0].get("channel_priority") if picked else None
        selected.extend(picked)

        if not country_scored:
            countries_without_candidates.append(country)

        candidates_by_country[country] = [
            _candidate_view(c, country, c in picked, _reason_for(c, winning_tier, picked, count))
            for c in sorted(country_scored, key=lambda x: x.get("global_score", 0) + x.get("russia_score", 0), reverse=True)
        ]

    non_brics = [s for s in scored if s.get("country") not in brics_countries]

    world_picks: list[dict] = []
    used_countries: set[str] = set()
    world_by_country: dict[str, list[dict]] = {}
    remaining_positions = max_world
    pool = list(non_brics)

    # Последовательно заполняем позиции "мира" — на каждом шаге каскад
    # применяется заново к тому, что осталось (за вычетом уже занятых
    # стран), а не один общий проход — так же, как для стран БРИКС+.
    while remaining_positions > 0:
        available = [c for c in pool if c.get("country") not in used_countries and c.get("channel_priority") != "NO"]
        tier, tier_pool = _cascade_tier_and_pool(available)
        if not tier_pool:
            break
        winner = max(tier_pool, key=lambda x: x.get("global_score", 0))
        world_picks.append(winner)
        used_countries.add(winner.get("country"))
        pool.remove(winner)
        remaining_positions -= 1

    for item in non_brics:
        c = item.get("country", "?")
        if item in world_picks:
            reason = f"выбрано — уровень источника {item.get('channel_priority', 'UNRANKED')}"
        elif item.get("channel_priority") == "NO":
            reason = "источник уровня NO — не участвует в ranking (продолжает собираться в общую базу)"
        elif c in used_countries:
            reason = f"страна {c} уже представлена другой мировой новостью"
        elif len(world_picks) >= max_world:
            reason = f"лимит max_world={max_world} уже исчерпан"
        else:
            reason = "не выиграло каскад приоритета для своей позиции"
        world_by_country.setdefault(c, []).append(_candidate_view(item, c, item in world_picks, reason))

    selected.extend(world_picks)

    all_candidates = {"by_country": candidates_by_country, "world_by_country": world_by_country}
    CANDIDATES_OUTPUT.write_text(json.dumps(all_candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    all_flat = [c for lst in candidates_by_country.values() for c in lst]
    all_flat += [c for lst in world_by_country.values() for c in lst]
    log_decisions(all_flat, decision_source="auto_cascade")

    # reasoning оставлен для обратной совместимости с местами, где читается
    # именно этот формат (краткая версия без original_title/summary).
    reasoning = {
        "by_country": candidates_by_country,
        "world": [c for lst in world_by_country.values() for c in lst],
        "countries_without_candidates": countries_without_candidates,
    }

    digest = {"items": [
        {
            "country": it.get("country"),
            "headline_ru": it.get("headline_ru") or it.get("headline", ""),
            "summary_250": it.get("summary_250", ""),
            "world_comment": it.get("world_comment"),
            "russia_comment": it.get("russia_comment"),
            "global_score": it.get("global_score"),
            "russia_score": it.get("russia_score"),
            "sources": it.get("sources", []),
            "channel_priority": it.get("channel_priority", "UNRANKED"),
            "include": True,  # можно снять в UI перед публикацией — см. app.py
        }
        for it in selected
    ]}
    DIGEST_OUTPUT.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    return digest["items"], reasoning


if __name__ == "__main__":
    from ..config import BRICS_PLUS_COUNTRIES

    filtered_path = DATA_DIR / "filtered.json"
    filtered = json.loads(filtered_path.read_text(encoding="utf-8"))
    scored_items = score_items(filtered)
    digest_items = select_daily_digest(scored_items, BRICS_PLUS_COUNTRIES)
    print(f"В дневной дайджест отобрано: {len(digest_items)} карточек")
