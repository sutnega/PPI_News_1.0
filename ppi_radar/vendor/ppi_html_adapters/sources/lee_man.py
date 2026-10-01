from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="lee-man", source_id="NEW-0054", source_name="Lee & Man Paper",
    endpoint="https://www1.hkexnews.hk/search/titlesearch.xhtml?category=0&lang=EN&market=SEHK&stockId=6560",
    country="China", language="en",
    item_selectors=("table tr", ".news-list li", ".search-result", "article"),
    title_selectors=("td a", "h2", "h3", ".title", "a[title]"),
    link_selectors=("td a[href]", "a[href]"),
    date_selectors=("td.release-time", "time", ".date", "[class*='time']"),
    include_url_patterns=(r"hkexnews\.hk/",),
    rate_limit_seconds=4.0,
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

