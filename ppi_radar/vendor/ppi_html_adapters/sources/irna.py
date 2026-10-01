from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="irna", source_id="NEW-0046", source_name="IRNA",
    endpoint="https://en.irna.ir/", country="Iran", language="en",
    item_selectors=("article", ".news-item", ".item", "[class*='news']", "[class*='media']"),
    title_selectors=("h2", "h3", "h4", ".title", "[class*='title']"),
    include_url_patterns=(r"en\.irna\.ir/news/", r"en\.irna\.ir/.*\d{6,}"),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

