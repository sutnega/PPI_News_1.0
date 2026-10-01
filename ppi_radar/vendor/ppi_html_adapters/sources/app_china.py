from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="app-china", source_id="NEW-0055", source_name="APP China",
    endpoint="https://www.app.com.cn/news", country="China", language="zh",
    item_selectors=(".news-list li", ".list li", "article", ".news-item", "[class*='news']"),
    title_selectors=("h2", "h3", "h4", ".title", "a[title]"),
    date_selectors=("time", ".date", "span[class*='time']", "span[class*='date']"),
    include_url_patterns=(r"app\.com\.cn/news",),
    timeout_seconds=40.0,
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

