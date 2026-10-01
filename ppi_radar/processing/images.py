"""
Проверка og:image у источников. Здесь — функция, принимающая произвольный
список ссылок (обычно — sources у отобранных карточек дайджеста).

Правило (см. TZ_PPI_Radar_AI_pipeline, раздел 14): использовать только
изображение, реально связанное со статьёй. Приоритет извлечения:
og:image → twitter:image → основное article image. Если изображения нет —
image_url=null, картинка НЕ генерируется искусственно.
"""
from __future__ import annotations

import re
import urllib.request

from ..error_log import log_error

OG_IMAGE_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)
OG_IMAGE_RE_ALT = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I)
TWITTER_IMAGE_RE = re.compile(r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']', re.I)
TWITTER_IMAGE_RE_ALT = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']', re.I)


def find_og_image(url: str, timeout: int = 12) -> str | None:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; TelegramBot (like TwitterBot))"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read(200_000).decode("utf-8", errors="ignore")
        m = OG_IMAGE_RE.search(html) or OG_IMAGE_RE_ALT.search(html)
        if m:
            return m.group(1)
        # Запасной вариант — twitter:image, если у страницы нет og:image
        # (некоторые сайты, особенно старые/HTML-адаптерные, ставят только его).
        m = TWITTER_IMAGE_RE.search(html) or TWITTER_IMAGE_RE_ALT.search(html)
        return m.group(1) if m else None
    except Exception as e:
        print(f"  og:image/twitter:image недоступно для {url}: {e}")
        log_error("images", "fetch_error", str(e), url=url)
        return None


def attach_images(digest_items: list[dict]) -> list[dict]:
    """Для каждой карточки берёт og:image первого источника, у которого он находится."""
    for item in digest_items:
        image_url = None
        for src in item.get("sources", []):
            image_url = find_og_image(src)
            if image_url:
                break
        item["image_url"] = image_url
    return digest_items


if __name__ == "__main__":
    import json

    from ..config import DATA_DIR

    digest_path = DATA_DIR / "digest_cards.json"
    data = json.loads(digest_path.read_text(encoding="utf-8"))
    data["items"] = attach_images(data["items"])
    digest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    found = sum(1 for i in data["items"] if i.get("image_url"))
    print(f"Картинки найдены для {found} из {len(data['items'])} карточек")
