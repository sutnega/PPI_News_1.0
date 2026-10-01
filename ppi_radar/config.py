"""
Центральная конфигурация PPI Global Radar.

Все пути — относительно корня проекта (там, где лежит папка ppi_radar/),
а не захардкожены под конкретную машину. Секреты (токены/ключи) берутся
из переменных окружения или файла .env в корне проекта.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Пути -------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT_DIR / "sources"
DATA_DIR = ROOT_DIR / "data"
LOGS_DIR = ROOT_DIR / "logs"
CARDS_DIR = DATA_DIR / "tg_cards"

SOURCES_CSV = SOURCES_DIR / "PPI_Country_Industry_Radar_recon_v9.csv"

for _d in (DATA_DIR, LOGS_DIR, CARDS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# --- Загрузка .env (без внешней зависимости python-dotenv) ------------
def _load_dotenv(path: Path = ROOT_DIR / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def reload_env() -> None:
    """
    Перечитывает .env и обновляет модуль-уровневые константы прямо в
    работающем процессе (нужно для веб-интерфейса Streamlit: он не
    перезапускает Python-процесс на каждое действие, поэтому обычной
    загрузки .env при первом импорте недостаточно — после сохранения
    новых значений в .env их нужно перечитать явно).
    """
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip().strip('"').strip("'")

    module = globals()
    module["TELEGRAM_BOT_TOKEN"] = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    module["TELEGRAM_CHAT_ID"] = os.environ.get("TELEGRAM_CHAT_ID", "")
    module["LLM_PROVIDER"] = os.environ.get("LLM_PROVIDER", "groq")
    module["LLM_PROVIDER_CHAIN"] = os.environ.get("LLM_PROVIDER_CHAIN", "")
    module["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY", "")
    module["GROQ_API_KEY"] = os.environ.get("GROQ_API_KEY", "")
    module["GROQ_MODEL"] = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    module["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")
    module["GEMINI_MODEL"] = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    module["OLLAMA_BASE_URL"] = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    module["OLLAMA_MODEL"] = os.environ.get("OLLAMA_MODEL", "llama3.1")
    module["OPENROUTER_API_KEY"] = os.environ.get("OPENROUTER_API_KEY", "")
    module["OPENROUTER_MODEL"] = os.environ.get("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")
    module["CEREBRAS_API_KEY"] = os.environ.get("CEREBRAS_API_KEY", "")
    module["CEREBRAS_MODEL"] = os.environ.get("CEREBRAS_MODEL", "llama-3.3-70b")
    module["MISTRAL_API_KEY"] = os.environ.get("MISTRAL_API_KEY", "")
    module["MISTRAL_MODEL"] = os.environ.get("MISTRAL_MODEL", "mistral-large-latest")

# --- Секреты / внешние сервисы -----------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")  # @username или -100... числовой ID

# Выбор провайдера LLM для редакторского шага (скоринг/перевод/комментарии).
# По умолчанию — groq: бесплатный тариф, быстро, хорошее качество.
# Варианты: groq (бесплатно) | gemini (бесплатно) | ollama (бесплатно, локально) |
#           openrouter (бесплатно, ротирующийся набор моделей) | anthropic (платно)
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq")

# Цепочка автопереключения: список провайдеров через запятую в порядке
# приоритета, например "groq,gemini,openrouter". Если у первого кончился
# лимит/квота — редактор автоматически пробует следующего, и так далее.
# Пусто = использовать только LLM_PROVIDER без автопереключения.
LLM_PROVIDER_CHAIN = os.environ.get("LLM_PROVIDER_CHAIN", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# llama-3.3-70b-versatile пропала из списка разрешённых моделей аккаунта в
# 2026 (Groq периодически меняет линейку бесплатных моделей) — сейчас
# доступна openai/gpt-oss-120b. Проверить актуальный список для своего
# аккаунта: https://console.groq.com/settings/limits
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")

# Cerebras — бесплатно, 30 запросов/мин, 14 400/день (та же щедрость, что
# у Groq) — работает на собственном "железе" Cerebras, очень быстро.
# Реально имеет Llama 3.3 70B (та модель, что раньше стояла у Groq).
# Ключ: https://cloud.cerebras.ai (API Keys, начинается с csk-)
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.environ.get("CEREBRAS_MODEL", "llama-3.3-70b")

# Mistral AI — бесплатно, но лимит считается за МЕСЯЦ (1 млрд токенов/мес),
# а не за день — совокупно самый большой запас среди всех провайдеров в
# цепочке. Ключ: https://console.mistral.ai (API Keys)
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-large-latest")

# OpenRouter — бесплатно, единый ключ на десятки моделей (Llama, Qwen,
# GPT-OSS и т.д. с суффиксом :free). ВАЖНО: бесплатные модели DeepSeek на
# OpenRouter пропали в середине 2026 — там теперь только платный DeepSeek.
# Модель по умолчанию — openai/gpt-oss-120b:free: держит структурированный
# JSON-вывод заметно надёжнее, чем авто-роутер "openrouter/free" (тот может
# попасть на случайную слабую модель). Каталог бесплатных моделей у
# OpenRouter МЕНЯЕТСЯ ЧАСТО (модели то появляются, то пропадают) — если
# этой модели не станет, актуальный список: https://openrouter.ai/models?max_price=0
# Бесплатный тариф ограничен (обычно ~20 запросов/мин, ~200/день на аккаунт) —
# поэтому в цепочке он лучше на второй-третьей позиции, а не первым.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")

# --- Общие константы ----------------------------------------------------
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RSS_WINDOW_HOURS = int(os.environ.get("PPI_RSS_WINDOW_HOURS", "168"))  # неделя вместо 72ч

BRICS_PLUS_COUNTRIES = [
    "Бразилия", "Россия", "Индия", "Китай", "ЮАР",
    "Египет", "Эфиопия", "Индонезия", "Иран", "ОАЭ", "Саудовская Аравия",
]

COUNTRY_FLAGS = {
    "Бразилия": "🇧🇷", "Россия": "🇷🇺", "Индия": "🇮🇳", "Китай": "🇨🇳",
    "ЮАР": "🇿🇦", "Египет": "🇪🇬", "Эфиопия": "🇪🇹", "Индонезия": "🇮🇩",
    "Иран": "🇮🇷", "ОАЭ": "🇦🇪", "Саудовская Аравия": "🇸🇦",
}
