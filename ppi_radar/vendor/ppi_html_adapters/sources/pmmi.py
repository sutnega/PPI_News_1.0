from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="pmmi", source_id="NEW-0049", source_name="PMMI — Association for Packaging and Processing Technologies",
    endpoint="https://www.pmmi.org/news", country="USA/World", language="en",
    item_selectors=("article", ".views-row", ".news-card", ".card", "[class*='news']"),
    title_selectors=("h2", "h3", ".card-title", "[class*='title']"),
    include_url_patterns=(r"pmmi\.org/(news|press-releases|articles)/",),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

