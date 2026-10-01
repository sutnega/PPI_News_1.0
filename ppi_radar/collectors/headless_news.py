"""
Парсеры новостных JS-источников, не отдающих RSS (нужен либо headless-браузер,
либо прямой JSON/API-вызов, найденный вручную при разведке).

Перенесено из parser_headless.py с двумя изменениями:
  1. Все функции возвращают записи в ЕДИНОЙ схеме, совместимой с
     collectors.rss.collect_rss(), чтобы оба источника шли в один
     пайплайн фильтрации/скоринга:
     {source_id, country, source_type, org, title, link, summary,
      published (ISO-строка или None), in_window (bool)}
  2. Результат сохраняется через ppi_radar.config, без захардкоженных путей.

Требует: pip install playwright && playwright install chromium
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from ..config import DATA_DIR, RSS_WINDOW_HOURS, UA
from ..country_map import normalize_country
from ..error_log import log_error
from ..source_priority import get_priority

OUTPUT_PATH = DATA_DIR / "headless_collected_raw.json"


def _normalize(source_id, country, org, title, link, date_text=None, summary="", published_dt=None):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=RSS_WINDOW_HOURS)
    in_window = bool(published_dt and published_dt >= cutoff) if published_dt else None
    return {
        "source_id": source_id,
        "country": normalize_country(country),
        "source_type": "custom_parser",
        "org": org,
        "channel_priority": get_priority(link or ""),
        "title": (title or "").strip(),
        "link": link,
        "summary": (summary or "")[:500],
        "published": published_dt.isoformat() if published_dt else None,
        "date_raw": date_text,
        # Даты у этих источников часто в нестандартных/относительных форматах
        # ("6 jam yang lalu" и т.п.) — надёжно парсить их автоматически нельзя,
        # поэтому по умолчанию считаем "в окне", а не отбрасываем молча.
        # Реальная фильтрация по свежести всё равно проверяется на этапе
        # редактуры (LLM видит текст даты и решает).
        "in_window": True if in_window is None else in_window,
    }


def _render_page(url, wait_ms=6000, extra_wait_selector=None, stabilize_selector=None,
                  stabilize_timeout_ms=15000, wait_until="domcontentloaded"):
    from playwright.sync_api import sync_playwright  # локальный импорт: playwright опционален

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA, viewport={"width": 1366, "height": 768})
        try:
            page.goto(url, timeout=30000, wait_until=wait_until)
        except Exception:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
        if extra_wait_selector:
            try:
                page.wait_for_selector(extra_wait_selector, timeout=10000)
            except Exception:
                pass
        if stabilize_selector:
            page.wait_for_timeout(2500)
            prev_count, stable_checks, elapsed = -1, 0, 2500
            while elapsed < stabilize_timeout_ms and stable_checks < 3:
                page.wait_for_timeout(1000)
                elapsed += 1000
                count = page.locator(stabilize_selector).count()
                if count == prev_count and count > 0:
                    stable_checks += 1
                else:
                    stable_checks = 0
                prev_count = count
        else:
            page.wait_for_timeout(wait_ms)
        html = page.content()
        browser.close()
        return html


# ---------------------------------------------------------------------------
# China Paper Association — chinappi.org  (SRC-0305 / SRC-0369)
# ---------------------------------------------------------------------------
def parse_chinappi() -> list[dict]:
    url = "http://www.chinappi.org/indust_news.html"
    html = _render_page(url, extra_wait_selector="ul.news_ul li", stabilize_selector="ul.news_ul li")
    soup = BeautifulSoup(html, "lxml")

    items = []
    for li in soup.select("ul.news_ul > li"):
        time_span = li.find("span", class_="time")
        date_raw = time_span.get_text(strip=True).strip("[]") if time_span else None
        a_tag = li.find("a")
        link = a_tag.get("href") if a_tag else None
        if link and not link.startswith("http"):
            link = "http://www.chinappi.org/" + link.lstrip("/")

        li_copy = BeautifulSoup(str(li), "lxml")
        for tag in li_copy.find_all(["span", "div"]):
            tag.extract()
        title = li_copy.get_text(strip=True)

        published_dt = None
        if date_raw:
            try:
                published_dt = datetime.strptime(date_raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        if title and link:
            items.append(_normalize("SRC-0305/SRC-0369", "Китай", "China Paper Association",
                                     title, link, date_raw, published_dt=published_dt))
    return items


# ---------------------------------------------------------------------------
# PIB (замена заблокированного commerce.gov.in) — Ministry of Commerce & Industry
# (SRC-0360 / SRC-0361)
# ---------------------------------------------------------------------------
def parse_pib_commerce(month=None, year=None, day=0) -> list[dict]:
    """
    commerce.gov.in закрыт Akamai для headless-браузеров. Обходной путь,
    найденный при разведке: PIB (Press Information Bureau) отдаёт релизы
    того же министерства через обычный ASP.NET postback — работает через
    requests, без Playwright.
    """
    url = "https://www.pib.gov.in/allRel.aspx?reg=48&lang=1"
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})

    try:
        r1 = sess.get(url, timeout=30)
        soup = BeautifulSoup(r1.text, "lxml")
        form = soup.find("form")

        payload = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            itype = (inp.get("type") or "text").lower()
            if itype in ("checkbox", "radio"):
                if inp.get("checked") is not None:
                    payload[name] = inp.get("value", "on")
            else:
                payload[name] = inp.get("value", "")
        for sel in form.find_all("select"):
            name = sel.get("name")
            if not name:
                continue
            selected = sel.find("option", selected=True)
            first = sel.find("option")
            payload[name] = selected.get("value", "") if selected else (first.get("value", "") if first else "")

        ministry_key = "ctl00$ContentPlaceHolder1$ddlMinistry"
        day_key = "ctl00$ContentPlaceHolder1$ddlday"
        month_key = "ctl00$ContentPlaceHolder1$ddlMonth"
        year_key = "ctl00$ContentPlaceHolder1$ddlYear"

        payload[ministry_key] = "16"  # Ministry of Commerce & Industry
        payload[day_key] = str(day)
        if month is not None:
            payload[month_key] = str(month)
        if year is not None:
            payload[year_key] = str(year)
        payload["__EVENTTARGET"] = ministry_key
        payload["__EVENTARGUMENT"] = ""

        r2 = sess.post(url, data=payload, timeout=30, headers={"Referer": url})
    except Exception as e:
        print(f"ERROR pib_commerce: {e}")
        log_error("headless", "fetch_error", str(e), parser="pib_commerce")
        return []

    soup2 = BeautifulSoup(r2.text, "lxml")
    items = []
    content = soup2.select_one("div.content-area")
    if content:
        for li in content.select("ul.leftul > li"):
            a_tag = li.find("a")
            date_tag = li.select_one("span.publishdatesmall")
            if not a_tag:
                continue
            link = a_tag.get("href")
            if link and not link.startswith("http"):
                link = "https://www.pib.gov.in" + link
            title = a_tag.get("title") or a_tag.get_text(strip=True)
            date_text = (date_tag.get_text(strip=True) if date_tag else "").replace("Posted On:", "").strip()
            items.append(_normalize("SRC-0360/SRC-0361", "Индия", "Ministry of Commerce & Industry (via PIB)",
                                     title, link, date_text))
    return items


# ---------------------------------------------------------------------------
# CPPRI — cppri.res.in/press-archive  (SRC-0364)
# ---------------------------------------------------------------------------
def parse_cppri() -> list[dict]:
    url = "https://cppri.res.in/press-archive"
    html = _render_page(url, wait_ms=6000, extra_wait_selector="table#example")
    soup = BeautifulSoup(html, "lxml")

    items = []
    for tr in soup.select("table#example tbody tr"):
        tds = tr.select("td")
        if len(tds) >= 3:
            items.append(_normalize("SRC-0364", "Индия", "CPPRI",
                                     tds[1].get_text(strip=True), url,
                                     tds[2].get_text(strip=True)))
    return items


# ---------------------------------------------------------------------------
# CAPMAS Egypt — прямой JSON API, без headless-браузера  (SRC-0378)
# ---------------------------------------------------------------------------
def parse_capmas() -> list[dict]:
    api_url = "https://www.capmas.gov.eg:8080/api/News/Search"
    try:
        resp = requests.get(api_url, params={"pageSize": 10, "currentPage": 1},
                             headers={"User-Agent": UA}, timeout=20, verify=False)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"ERROR capmas: {e}")
        log_error("headless", "fetch_error", str(e), parser="capmas")
        return []

    items = []
    for entry in data.get("data", []):
        en = next((t for t in entry.get("newsTranslation", []) if t.get("locale") == "en"), None)
        title = (en["title"] if en else entry.get("title")) or ""
        link = f"https://www.capmas.gov.eg/mediaLanding/news/{entry.get('id')}"
        items.append(_normalize("SRC-0378", "Египет", "CAPMAS",
                                 title.strip(), link, entry.get("publishDate")))
    return items


# ---------------------------------------------------------------------------
# Ethiopian Customs Commission — ecc.gov.et/news  (SRC-0382)
# ---------------------------------------------------------------------------
def parse_ecc_ethiopia() -> list[dict]:
    url = "https://www.ecc.gov.et/news"
    html = _render_page(url, extra_wait_selector="div.news-box", stabilize_selector="div.news-box")
    soup = BeautifulSoup(html, "lxml")

    items = []
    for box in soup.select("div.news-box"):
        title_tag = box.select_one("h3")
        date_tag = box.select_one("div.flex.items-center.text-gray-500.text-xs")
        link_tag = box.select_one("a[href^='/newsdetailpage/']")
        title = title_tag.get_text(strip=True) if title_tag else None
        link = link_tag.get("href") if link_tag else None
        if link and not link.startswith("http"):
            link = "https://www.ecc.gov.et" + link
        if title and link:
            items.append(_normalize("SRC-0382", "Эфиопия", "Ethiopian Customs Commission",
                                     title, link, date_tag.get_text(strip=True) if date_tag else None))
    return items


# ---------------------------------------------------------------------------
# BRIN Индонезия — brin.go.id/news и /press-release  (SRC-0389)
# ---------------------------------------------------------------------------
def parse_brin(list_url: str = "https://www.brin.go.id/news") -> list[dict]:
    html = _render_page(list_url, extra_wait_selector="div.media", stabilize_selector="div.media")
    soup = BeautifulSoup(html, "lxml")

    items, seen = [], set()
    for media in soup.select("div.media"):
        a_tag = media.select_one(".media-title a") or media.select_one("h2 a, h3 a, h4 a, h5 a, h6 a")
        date_tag = media.select_one("div.date.text-muted") or media.select_one("span.time")
        summary_tag = media.select_one("div.media-content")
        if not summary_tag:
            for cand in media.select("div.LinesEllipsis"):
                if not cand.find_parent(["h2", "h3", "h4", "h5", "h6"]):
                    summary_tag = cand
                    break
        if not a_tag:
            continue
        title = a_tag.get_text(strip=True)
        link = a_tag.get("href")
        if link and not link.startswith("http"):
            link = "https://www.brin.go.id" + link
        if not link or link in seen:
            continue
        seen.add(link)
        items.append(_normalize("SRC-0389", "Индонезия", "BRIN", title, link,
                                 date_tag.get_text(strip=True) if date_tag else None,
                                 summary=summary_tag.get_text(strip=True) if summary_tag else ""))
    return items


# ---------------------------------------------------------------------------
# CNPPRI (China National Pulp and Paper Research Institute) — cnppri.com/1532.html
# (SRC-0370). ВАЖНО: этот источник помечен в базе как fetch_method=RSS, но по
# факту НЕ отдаёт RSS/XML — это обычная HTML-страница со списком новостей.
# Попытка читать её через feedparser стабильно падает с
# "not well-formed (invalid token)", потому что HTML — не валидный XML.
# Разведка (заметка в CSV) уже определила рабочие CSS-селекторы:
# div.xwzx-news-item / a.news-title / div.xwzx-news-item-date — переносим
# источник сюда, в обычный HTML-парсер, вместо того чтобы держать его
# в RSS-коллекторе, где он гарантированно ничего не даст.
# ---------------------------------------------------------------------------
def parse_cnppri_china() -> list[dict]:
    url = "https://www.cnppri.com/1532.html"
    html = _render_page(url, extra_wait_selector="div.xwzx-news-item", stabilize_selector="div.xwzx-news-item")
    soup = BeautifulSoup(html, "lxml")

    items = []
    for row in soup.select("div.xwzx-news-item"):
        a_tag = row.select_one("a.news-title") or row.find("a")
        date_tag = row.select_one("div.xwzx-news-item-date")
        if not a_tag:
            continue
        title = a_tag.get_text(strip=True)
        link = a_tag.get("href")
        if link and not link.startswith("http"):
            link = "https://www.cnppri.com/" + link.lstrip("/")
        if title and link:
            items.append(_normalize("SRC-0370", "Китай", "China National Pulp and Paper Research Institute",
                                     title, link, date_tag.get_text(strip=True) if date_tag else None))
    return items


ALL_PARSERS = {
    "chinappi": parse_chinappi,
    "pib_commerce": parse_pib_commerce,
    "cppri": parse_cppri,
    "cnppri_china": parse_cnppri_china,
    "capmas": parse_capmas,
    "ecc_ethiopia": parse_ecc_ethiopia,
    "brin_news": lambda: parse_brin("https://www.brin.go.id/news"),
    "brin_press_release": lambda: parse_brin("https://www.brin.go.id/press-release"),
}


def collect_headless(skip: set[str] | None = None) -> list[dict]:
    """Обратная совместимость: только список записей, без статистики."""
    items, _ = collect_headless_with_stats(skip)
    return items


def collect_headless_with_stats(skip: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """
    Запускает все headless/API-парсеры по очереди (последовательно —
    Playwright plохо параллелится в синхронном режиме) и сохраняет
    объединённый результат в едином формате. Дополнительно возвращает
    диагностику по каждому парсеру (сколько записей нашёл / упал ли).

    commerce_india (сам Akamai-заблокированный источник) сюда не входит:
    он остаётся нерабочим по решению, зафиксированному при разведке
    (см. 04_docs/Headless_Browser_8_JS_Sources_Report.md), замена — PIB.
    """
    skip = skip or set()
    all_items: list[dict] = []
    per_source: list[dict] = []
    for name, fn in ALL_PARSERS.items():
        if name in skip:
            continue
        print(f"headless: {name} ...")
        try:
            items = fn()
            status = "OK" if items else "0 записей (парсер не упал, но ничего не нашёл — вероятно, изменилась вёрстка сайта)"
        except Exception as e:
            print(f"  ERROR {name}: {e}")
            log_error("headless", "parser_error", str(e), parser=name)
            items = []
            status = f"ошибка: {e}"
        print(f"  -> {len(items)} записей")
        all_items.extend(items)
        country = items[0]["country"] if items else "?"
        per_source.append({"source_id": name, "country": country, "org": name,
                            "total_entries": len(items), "in_window_entries": len(items), "status": status})

    OUTPUT_PATH.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")

    from ..archive import append_to_archive
    new_archived = append_to_archive(all_items)
    print(f"Новых в архиве: {new_archived} (архив накопительный, старое не теряется)")

    return all_items, per_source


if __name__ == "__main__":
    collect_headless()
