"""
Единый клиент для вызова LLM с выбором провайдера через .env (LLM_PROVIDER)
или с автопереключением по цепочке (LLM_PROVIDER_CHAIN).

Поддержаны:
  - groq        — БЕСПЛАТНО (щедрый free tier), быстрые открытые модели.
                  Получить ключ: https://console.groq.com/keys
  - gemini      — БЕСПЛАТНО (free tier с более скромными лимитами).
                  Получить ключ: https://aistudio.google.com/apikey
  - openrouter  — БЕСПЛАТНО, единый ключ на десятки моделей с суффиксом
                  :free (Llama, Qwen, GPT-OSS и т.д.). Получить ключ:
                  https://openrouter.ai/keys — карта не нужна.
                  ВАЖНО: бесплатных моделей DeepSeek на OpenRouter больше
                  нет — весь DeepSeek там стал платным в середине 2026.
                  Честной бесплатной DeepSeek через API сейчас нет нигде.
  - ollama      — ПОЛНОСТЬЮ БЕСПЛАТНО и локально, без лимитов запросов,
                  но требует установленный Ollama и скачанную модель
                  (https://ollama.com), ест ресурсы вашей машины.
  - anthropic   — платный API (Claude). Оставлен как опция, если понадобится
                  более высокое качество и не критична стоимость.

Все пять вызываются через plain HTTP (requests), без специфичных SDK —
меньше зависимостей. Все реализации ожидают system+user промпт и
возвращают текст ответа как есть (парсинг JSON — забота вызывающего кода).
"""
from __future__ import annotations

import time

import requests

from .. import config as cfg
from ..error_log import log_error

MAX_RETRIES = 2  # при цепочке из нескольких провайдеров выгоднее быстро переключиться на
                  # следующего, чем долго повторять попытки на одном и том же
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Заголовки лимитов у Groq и OpenRouter (оба — OpenAI-совместимый формат).
# См. https://console.groq.com/docs/rate-limits — там же точные лимиты по
# каждой модели отдельно (console.groq.com/settings/limits).
_RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests", "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens",
    "retry-after",
)


def _rate_limit_info(resp: requests.Response) -> dict:
    """Достаёт все присутствующие заголовки лимита (не все провайдеры их шлют)."""
    return {h: resp.headers[h] for h in _RATE_LIMIT_HEADERS if h in resp.headers}


_last_rate_limit: dict[str, dict] = {}


def get_last_rate_limit(provider: str) -> dict | None:
    """Последний известный остаток лимита по провайдеру (или None, если ещё не звонили).
    Используется для ПРОАКТИВНОЙ паузы перед следующим батчем — не ждать 429,
    а заранее понять, что токенов может не хватить."""
    return _last_rate_limit.get(provider)


def parse_reset_duration(value: str | None) -> float | None:
    """Парсит строку вида '7.66s' / '1m2.9s' / '2m' (формат заголовков Groq
    x-ratelimit-reset-tokens/requests) в секунды. None, если не удалось."""
    if not value:
        return None
    import re as _re
    m = _re.match(r"^(?:(\d+)m)?(?:([\d.]+)s)?$", value.strip())
    if not m or not any(m.groups()):
        return None
    minutes = float(m.group(1) or 0)
    seconds = float(m.group(2) or 0)
    return minutes * 60 + seconds


def _log_rate_limit(provider: str, resp: requests.Response) -> dict:
    """Печатает в консоль остаток лимита (если сервер его прислал) — всегда,
    и на успехе, и на ошибке, чтобы было видно, когда лимит реально подходит
    к концу, а не только в момент, когда он уже кончился. Заодно сохраняет
    последнее известное состояние в _last_rate_limit для проактивной паузы."""
    info = _rate_limit_info(resp)
    if info:
        _last_rate_limit[provider] = info
        rem_req = info.get("x-ratelimit-remaining-requests")
        lim_req = info.get("x-ratelimit-limit-requests")
        rem_tok = info.get("x-ratelimit-remaining-tokens")
        lim_tok = info.get("x-ratelimit-limit-tokens")
        parts = []
        if rem_req is not None:
            parts.append(f"запросов осталось {rem_req}/{lim_req}")
        if rem_tok is not None:
            parts.append(f"токенов осталось {rem_tok}/{lim_tok}")
        if parts:
            print(f"  [{provider}] лимит: " + ", ".join(parts))
    return info


def _classify_error(resp: requests.Response) -> tuple[str, str]:
    """
    Возвращает (error_type, человекочитаемое_сообщение) — точная причина,
    а не общее "HTTP xxx". Разделяет: лимит запросов/токенов (429),
    слишком большой запрос или превышен контекст (413/400 + текст), сбой
    на стороне провайдера (5xx) — это разные проблемы с разными решениями.
    """
    status = resp.status_code
    body = resp.text[:300]
    if status == 429:
        return "rate_limited", f"HTTP 429 — лимит запросов/токенов исчерпан: {body}"
    if status == 413:
        return "payload_too_large", f"HTTP 413 — запрос слишком большой (уменьшите BATCH_SIZE): {body}"
    if status == 400 and ("context" in body.lower() or "too long" in body.lower() or "maximum" in body.lower()):
        return "context_length_exceeded", f"HTTP 400 — превышена длина контекста модели: {body}"
    if status == 400:
        return "bad_request", f"HTTP 400 — некорректный запрос (не лимит): {body}"
    if status == 401 or status == 403:
        return "auth_error", f"HTTP {status} — проблема с ключом API (неверный/просрочен/не тот scope): {body}"
    if status >= 500:
        return "provider_5xx", f"HTTP {status} — сбой на стороне провайдера, не у вас: {body}"
    return "http_error", f"HTTP {status}: {body}"


def _post_with_retry(url: str, provider: str = "?", **kwargs) -> requests.Response:
    """
    POST с ретраями при временных ошибках (в первую очередь 429 — типичная
    ситуация на бесплатных тарифах Groq/Gemini при частых запросах).
    Уважает заголовок Retry-After, но НЕ дольше MAX_WAIT_SECONDS — если
    провайдер прислал в заголовке большое число (например, при исчерпании
    часовой/суточной квоты), это выглядело бы как зависший интерфейс.
    Лучше быстро сдаться и откатиться на эвристику для этого батча
    (см. editor.py), чем ждать неопределённо долго в интерактивном UI.

    На каждый ответ (успех и ошибка) печатает в консоль остаток лимита
    запросов/токенов, если провайдер его прислал (Groq/OpenRouter), и при
    ошибке пишет точную классификацию (лимит / слишком большой запрос /
    превышен контекст / таймаут / сбой сервера) в единый журнал ошибок
    (data/logs/all_errors.jsonl, см. error_log.py) — не просто "HTTP xxx".
    """
    MAX_WAIT_SECONDS = 10
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, **kwargs)
        except requests.exceptions.Timeout as e:
            last_exc = e
            log_error("llm_editor", "timeout", str(e), provider=provider, url=url)
            time.sleep(min(2 * attempt, MAX_WAIT_SECONDS))
            continue
        except requests.exceptions.ConnectionError as e:
            last_exc = e
            log_error("llm_editor", "connection_error", str(e), provider=provider, url=url)
            time.sleep(min(2 * attempt, MAX_WAIT_SECONDS))
            continue

        rl_info = _log_rate_limit(provider, resp)

        if resp.status_code not in RETRYABLE_STATUS:
            if not resp.ok:
                error_type, msg = _classify_error(resp)
                log_error("llm_editor", error_type, msg, provider=provider, **rl_info)
                raise requests.exceptions.HTTPError(msg)
            return resp

        error_type, msg = _classify_error(resp)
        retry_after = resp.headers.get("Retry-After")
        if retry_after and float(retry_after) > 60:
            # Retry-After больше минуты обычно означает часовую/суточную квоту,
            # а не кратковременный лимит запросов — повторять попытки внутри
            # интерактивной сессии бессмысленно, лучше сразу сдаться и дать
            # editor.py откатиться на эвристику для этого батча.
            log_error("llm_editor", "quota_exhausted_long", msg, provider=provider,
                      retry_after_seconds=retry_after, **rl_info)
            raise requests.exceptions.HTTPError(
                f"HTTP 429: лимит исчерпан надолго (сервер просит подождать "
                f"{float(retry_after):.0f}с — похоже на суточную/часовую квоту, не на "
                f"кратковременный лимит запросов/минуту)"
            )
        wait = min(float(retry_after), MAX_WAIT_SECONDS) if retry_after else min(2 ** attempt, MAX_WAIT_SECONDS)
        print(f"  LLM [{provider}]: {msg[:120]} (попытка {attempt}/{MAX_RETRIES}), "
              f"жду {wait:.0f}с и повторяю...")
        log_error("llm_editor", error_type, msg, provider=provider, attempt=attempt, **rl_info)
        time.sleep(wait)
        last_exc = requests.exceptions.HTTPError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    if last_exc:
        raise last_exc
    return resp


def _call_anthropic(system: str, user: str, max_tokens: int = 6000) -> str:
    if not cfg.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY не задан")
    resp = _post_with_retry(
        "https://api.anthropic.com/v1/messages",
        provider="anthropic",
        headers={
            "x-api-key": cfg.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(b["text"] for b in data["content"] if b.get("type") == "text")


def _call_groq(system: str, user: str, max_tokens: int = 6000) -> str:
    if not cfg.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY не задан. Бесплатный ключ: https://console.groq.com/keys")
    resp = _post_with_retry(
        "https://api.groq.com/openai/v1/chat/completions",
        provider="groq",
        headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": cfg.GROQ_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_gemini(system: str, user: str, max_tokens: int = 6000) -> str:
    if not cfg.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY не задан. Бесплатный ключ: https://aistudio.google.com/apikey")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{cfg.GEMINI_MODEL}:generateContent?key={cfg.GEMINI_API_KEY}")
    resp = _post_with_retry(
        url,
        provider="gemini",
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_ollama(system: str, user: str, max_tokens: int = 6000) -> str:
    try:
        resp = requests.post(
            f"{cfg.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": cfg.OLLAMA_MODEL,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": max_tokens},
            },
            timeout=180,  # локальная генерация может быть медленнее API
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"Не удалось подключиться к Ollama на {cfg.OLLAMA_BASE_URL}. "
            f"Установите Ollama (https://ollama.com), выполните `ollama pull {cfg.OLLAMA_MODEL}` "
            f"и убедитесь, что `ollama serve` запущен."
        ) from e
    return resp.json()["message"]["content"]


def _call_openrouter(system: str, user: str, max_tokens: int = 6000) -> str:
    if not cfg.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY не задан. Бесплатный ключ: https://openrouter.ai/keys "
                            "(карта не нужна для моделей с суффиксом :free)")
    resp = _post_with_retry(
        "https://openrouter.ai/api/v1/chat/completions",
        provider="openrouter",
        headers={"Authorization": f"Bearer {cfg.OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": cfg.OPENROUTER_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_cerebras(system: str, user: str, max_tokens: int = 6000) -> str:
    if not cfg.CEREBRAS_API_KEY:
        raise RuntimeError("CEREBRAS_API_KEY не задан. Бесплатный ключ: https://cloud.cerebras.ai "
                            "(раздел API Keys, ключ начинается с csk-)")
    resp = _post_with_retry(
        "https://api.cerebras.ai/v1/chat/completions",
        provider="cerebras",
        headers={"Authorization": f"Bearer {cfg.CEREBRAS_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": cfg.CEREBRAS_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_mistral(system: str, user: str, max_tokens: int = 6000) -> str:
    if not cfg.MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY не задан. Бесплатный ключ: https://console.mistral.ai "
                            "(раздел API Keys)")
    resp = _post_with_retry(
        "https://api.mistral.ai/v1/chat/completions",
        provider="mistral",
        headers={"Authorization": f"Bearer {cfg.MISTRAL_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": cfg.MISTRAL_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


_PROVIDERS = {
    "anthropic": _call_anthropic,
    "groq": _call_groq,
    "gemini": _call_gemini,
    "ollama": _call_ollama,
    "openrouter": _call_openrouter,
    "cerebras": _call_cerebras,
    "mistral": _call_mistral,
}


def call_llm(system: str, user: str, provider: str | None = None, max_tokens: int = 6000) -> str:
    provider = (provider or cfg.LLM_PROVIDER).strip().lower()
    if provider not in _PROVIDERS:
        raise ValueError(f"Неизвестный LLM_PROVIDER='{provider}'. Доступно: {list(_PROVIDERS)}")
    return _PROVIDERS[provider](system, user, max_tokens=max_tokens)


def get_provider_chain() -> list[str]:
    """
    Порядок провайдеров для автопереключения. Берётся из LLM_PROVIDER_CHAIN
    ("groq,gemini,openrouter"), если задан; иначе — просто [LLM_PROVIDER]
    без автопереключения (старое поведение, обратная совместимость).
    """
    raw = cfg.LLM_PROVIDER_CHAIN.strip()
    if raw:
        chain = [p.strip().lower() for p in raw.split(",") if p.strip()]
        unknown = [p for p in chain if p not in _PROVIDERS]
        if unknown:
            raise ValueError(f"Неизвестные провайдеры в LLM_PROVIDER_CHAIN: {unknown}. "
                              f"Доступно: {list(_PROVIDERS)}")
        return chain
    return [cfg.LLM_PROVIDER.strip().lower()]


def call_llm_with_fallback(system: str, user: str, max_tokens: int = 6000) -> tuple[str, str, list[str]]:
    """
    Пробует провайдеров из get_provider_chain() по порядку. Возвращает
    (текст_ответа, использованный_провайдер, список_ошибок_остальных).
    Если ни один не сработал — поднимает RuntimeError со всеми ошибками.
    """
    chain = get_provider_chain()
    errors: list[str] = []
    for provider in chain:
        try:
            text = call_llm(system, user, provider=provider, max_tokens=max_tokens)
            return text, provider, errors
        except Exception as e:
            errors.append(f"{provider}: {e}")
            continue
    raise RuntimeError("Все провайдеры в цепочке недоступны — " + "; ".join(errors))
