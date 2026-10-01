from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="thenational", source_id="NEW-0041", source_name="The National — Business",
    endpoint="https://www.thenationalnews.com/business/", country="UAE", language="en",
    item_selectors=("article", "[data-testid*='card']", ".article-card", "[class*='story']", "[class*='Card']"),
    title_selectors=("h2", "h3", "[data-testid*='headline']", "[class*='headline']"),
    include_url_patterns=(r"thenationalnews\.com/business/",),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

