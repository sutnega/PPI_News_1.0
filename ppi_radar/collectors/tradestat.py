"""
TRADESTAT (DGCI&S, tradestat.commerce.gov.in) — торговая статистика Индии
по HS-главам 47/48/49 (целлюлоза, бумага, печатная продукция).

Это НЕ часть ежедневного новостного дайджеста — это отдельный источник
данных для аналитики (страновые профили, товарная аналитика, дашборд
торговых потоков — см. "Полка 5" в 04_docs/PPI_Radar_Knowledge_Base.md).
Запускать отдельно, результат — сырые JSON для последующего анализа.

Перенесено из parser_headless.py без изменения механики (она проверена
и задокументирована в Knowledge Base), только пути результатов заведены
через ppi_radar.config.

Требует: pip install playwright && playwright install chromium
"""
from __future__ import annotations

import json

from ..config import DATA_DIR, UA

BRICS_COUNTRIES_TRADESTAT = {
    "BRAZIL": "43", "RUSSIA": "344", "CHINA": "77", "SOUTH AFRICA": "365",
    "EGYPT": "111", "ETHIOPIA": "115", "IRAN": "189", "UAE": "419", "INDONESIA": "187",
}
HS_CODES_TRADESTAT = ["47", "48", "49"]
PPI_CHAPTERS_TRADESTAT = ["47", "48", "49"]


def parse_tradestat_pulp_paper() -> dict:
    """Глобальные (не по странам) итоги экспорта/импорта Индии по главам 47/48."""
    from playwright.sync_api import sync_playwright

    base_url = "https://tradestat.commerce.gov.in/eidb/chapter_wise_all_commodities_{flow}"
    result = {"status": "OK", "items": []}

    for flow in ("export", "import"):
        url = base_url.format(flow=flow)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=UA)
                page.goto(url, timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(1500)
                page.click("button:has-text('Submit')", timeout=5000)
                page.wait_for_timeout(2500)

                found_chapters = {}
                for _ in range(15):
                    rows = page.locator("table tr")
                    for i in range(rows.count()):
                        cols = rows.nth(i).inner_text().split("\t")
                        if len(cols) >= 2 and cols[1].strip() in ("47", "48"):
                            found_chapters[cols[1].strip()] = cols
                    if "47" in found_chapters and "48" in found_chapters:
                        break
                    next_btn = page.locator("a:has-text('Next')")
                    if next_btn.count() > 0:
                        next_btn.first.click()
                        page.wait_for_timeout(1200)
                    else:
                        break
                browser.close()

            for code, raw in found_chapters.items():
                result["items"].append({
                    "organization": "DGCI&S / TRADESTAT", "flow": flow,
                    "hs_chapter": code, "raw_row": " | ".join(raw), "url": url,
                })
        except Exception as e:
            result["status"] = f"ERROR on {flow}: {e}"

    if not result["items"]:
        result["status"] = "NO_ITEMS_FOUND"
    return result


def parse_tradestat_bilateral_brics(countries=None, hs_codes=None, flows=None, retries=2) -> dict:
    """Двусторонняя торговля Индии с каждой из стран БРИКС+ по HS-кодам."""
    from playwright.sync_api import sync_playwright

    countries = countries or BRICS_COUNTRIES_TRADESTAT
    hs_codes = hs_codes or HS_CODES_TRADESTAT
    flows = flows or ["export", "import"]
    result = {"status": "OK", "items": []}

    def _extract_bilateral_row(raw_text):
        for line in raw_text.split("\n"):
            cols = line.split("\t")
            if len(cols) >= 3 and cols[0].strip() == "1":
                return cols[2:]
        return None

    def _extract_years(raw_text):
        for line in raw_text.split("\n"):
            if line.strip().startswith("S.No."):
                return line.split("\t")[2:]
        return None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for flow in flows:
            url = f"https://tradestat.commerce.gov.in/eidb/commodityx_countries_wise_{flow}"
            for country_name, country_val in countries.items():
                for hs in hs_codes:
                    attempt, last_error = 0, None
                    while attempt <= retries:
                        attempt += 1
                        page = browser.new_page(user_agent=UA)
                        try:
                            page.goto(url, timeout=30000, wait_until="networkidle")
                            page.wait_for_timeout(1200)
                            hs_input = page.locator("input[wire\\:model='searchTerm']")
                            hs_input.click()
                            hs_input.fill("")
                            hs_input.type(hs, delay=90)
                            page.wait_for_timeout(800)

                            selects = page.locator("select")
                            picked = False
                            for i in range(selects.count()):
                                sel = selects.nth(i)
                                if sel.locator("option").count() > 100:
                                    sel.select_option(country_val)
                                    picked = True
                                    break
                            if not picked:
                                raise RuntimeError("country <select> not found")
                            page.wait_for_timeout(700)

                            page.click("button:has-text('Submit')", timeout=8000)
                            page.wait_for_timeout(2300)

                            table = page.locator("table").first
                            raw = table.inner_text() if table.count() > 0 else ""
                            result["items"].append({
                                "organization": "DGCI&S / TRADESTAT", "flow": flow,
                                "country": country_name, "hs_code": hs,
                                "years": _extract_years(raw),
                                "bilateral_values_million_usd": _extract_bilateral_row(raw),
                                "url": url,
                            })
                            last_error = None
                            break
                        except Exception as e:
                            last_error = str(e)
                        finally:
                            page.close()
                    if last_error:
                        result["items"].append({
                            "organization": "DGCI&S / TRADESTAT", "flow": flow,
                            "country": country_name, "hs_code": hs,
                            "error": last_error, "url": url,
                        })
        browser.close()

    if not result["items"]:
        result["status"] = "NO_ITEMS_FOUND"
    return result


def parse_tradestat_chapter_headings(chapters=None, flows=None) -> dict:
    """Детализация глав 47/48/49 до 4-значных товарных позиций (глобально, не по странам)."""
    from playwright.sync_api import sync_playwright

    chapters = chapters or PPI_CHAPTERS_TRADESTAT
    flows = flows or ["export", "import"]
    result = {"chapters": {}}

    def _parse_table(text):
        rows = []
        for line in text.split("\n"):
            cols = [c.strip() for c in line.split("\t")]
            if cols and cols[0].isdigit() and len(cols) >= 8:
                rows.append({
                    "hs_code": cols[1], "commodity": cols[2],
                    "fy1_value_musd": cols[3], "fy1_share_pct": cols[4],
                    "fy2_value_musd": cols[5], "fy2_share_pct": cols[6],
                    "growth_pct": cols[7],
                })
        return rows

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for flow in flows:
            url = f"https://tradestat.commerce.gov.in/eidb/chapter_wise_all_commodities_{flow}"
            for chapter in chapters:
                page = browser.new_page(user_agent=UA)
                try:
                    page.goto(url, timeout=30000, wait_until="networkidle")
                    page.wait_for_timeout(1200)
                    page.locator("select").nth(2).select_option(chapter)
                    page.wait_for_timeout(400)
                    page.click("button:has-text('Submit')", timeout=8000)
                    page.wait_for_timeout(1800)
                    page.click("button:has-text('4')", timeout=8000)
                    page.wait_for_timeout(2000)
                    show_selects = page.locator("select").filter(has=page.locator("option", has_text="100"))
                    if show_selects.count() > 0:
                        show_selects.first.select_option("100")
                        page.wait_for_timeout(1200)
                    rows = _parse_table(page.locator("body").inner_text())
                    result["chapters"].setdefault(chapter, {})[flow] = rows
                except Exception as e:
                    result["chapters"].setdefault(chapter, {})[flow] = {"error": str(e)}
                finally:
                    page.close()
        browser.close()
    return result


if __name__ == "__main__":
    out = {
        "global": parse_tradestat_pulp_paper(),
        "bilateral_brics": parse_tradestat_bilateral_brics(),
        "chapter_headings": parse_tradestat_chapter_headings(),
    }
    (DATA_DIR / "tradestat_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Готово: data/tradestat_results.json")
