from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="paperfirst", source_id="SRC-0173", source_name="PaperFIRST",
    endpoint="https://www.paperfirst.info/", country="World", language="en",
    item_selectors=("article", ".blog-post", ".post", ".news-item", "[class*='article']"),
    title_selectors=("h2", "h3", ".entry-title", ".post-title"),
    date_selectors=("time", ".entry-date", ".post-date", "[class*='date']"),
    include_url_patterns=(r"paperfirst\.info/",),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

