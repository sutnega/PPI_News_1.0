from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="fsc", source_id="BENCH-0033", source_name="FSC International — News",
    endpoint="https://fsc.org/en/newscentre", country="World", language="en",
    item_selectors=("article", ".views-row", ".news-card", "[class*='card']", "[class*='news']"),
    title_selectors=("h2", "h3", ".field--name-title", "[class*='title']"),
    include_url_patterns=(r"fsc\.org/en/(newscentre|newsfeed|news)/",),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

