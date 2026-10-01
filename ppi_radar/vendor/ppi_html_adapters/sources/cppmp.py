from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="cppmp", source_id="CHN-0002", source_name="China Paper Magazine Network / 中国造纸杂志社",
    endpoint="https://www.cppmp.com/", country="China", language="zh",
    item_selectors=(".news-list li", ".list li", "article", ".news-item", "[class*='news'] li"),
    title_selectors=("h2", "h3", "h4", ".title", "a[title]"),
    date_selectors=("time", ".date", "span[class*='time']", "span[class*='date']"),
    include_url_patterns=(r"cppmp\.com/",),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

