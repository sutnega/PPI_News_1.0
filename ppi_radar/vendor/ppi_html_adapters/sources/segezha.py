from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="segezha", source_id="BENCH-0069", source_name="Segezha Group — Investor Relations",
    endpoint="https://segezha-group.com/press-center/news/", country="Russia", language="ru",
    item_selectors=("article", ".news-list__item", ".news-item", "[class*='news-card']", "[class*='news'] li"),
    title_selectors=("h2", "h3", ".news-list__title", "[class*='title']"),
    date_selectors=("time", ".news-list__date", "[class*='date']"),
    include_url_patterns=(r"segezha-group\.com/press-center/news/",),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

