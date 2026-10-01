from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="ecba", source_id="NEW-0052",
    source_name="Egyptian Export Council for Printing, Packaging, Paper, Literary and Artistic Works",
    endpoint="https://www.ecba-eg.com/en", country="Egypt", language="en",
    item_selectors=("article", ".news-item", ".card", ".item", "[class*='news']"),
    title_selectors=("h2", "h3", "h4", ".title", "[class*='title']"),
    include_url_patterns=(r"ecba-eg\.com/en/(news|news_details|events)",),
    min_items=1,
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

