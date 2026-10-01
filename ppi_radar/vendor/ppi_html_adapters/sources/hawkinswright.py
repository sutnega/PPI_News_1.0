from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="hawkinswright", source_id="BENCH-0028", source_name="Hawkins Wright — Pulp & Paper",
    endpoint="https://www.hawkinswright.com/pulp-paper", country="World", language="en",
    item_selectors=("article", ".blog-item", ".news-item", ".card", "[class*='report']"),
    include_url_patterns=(r"hawkinswright\.com/(news|pulp-paper|reports|events)",),
    requires_metadata_only=True,
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

