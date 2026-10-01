from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="caixin", source_id="NEW-0028", source_name="Caixin Global",
    endpoint="https://www.caixinglobal.com/", country="China", language="en",
    item_selectors=("article", ".article-list-item", ".news-item", "[class*='Article']", "[class*='story']"),
    title_selectors=("h2", "h3", "[class*='headline']", "[class*='title']"),
    include_url_patterns=(r"caixinglobal\.com/\d{4}-\d{2}-\d{2}/", r"caixinglobal\.com/(china|economy|business|finance)/"),
    requires_metadata_only=True,
    notes="Collects public headline/date/URL only; does not bypass the subscription wall.",
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

