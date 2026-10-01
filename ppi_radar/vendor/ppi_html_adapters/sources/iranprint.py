from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="iranprint", source_id="NEW-0047", source_name="Iran Print",
    endpoint="https://iranprint.com/", country="Iran", language="fa",
    item_selectors=("article", ".post", ".news-item", ".blog-item", "[class*='post']"),
    title_selectors=("h2", "h3", ".entry-title", ".post-title", "[class*='title']"),
    date_selectors=("time", ".entry-date", ".post-date", "[class*='date']"),
    include_url_patterns=(r"iranprint\.com/",),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

