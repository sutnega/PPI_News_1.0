from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="ft", source_id="NEW-0048", source_name="Financial Times",
    endpoint="https://www.ft.com/news-feed", country="United Kingdom", language="en",
    item_selectors=("article", ".o-teaser", "[data-trackable='teaser']", "[class*='teaser']"),
    title_selectors=("h2", "h3", ".js-teaser-heading-link", "[class*='heading']"),
    link_selectors=("a.js-teaser-heading-link[href]", "a[href]"),
    date_selectors=("time", "[data-o-component='o-date']", "[class*='timestamp']"),
    include_url_patterns=(r"ft\.com/content/",),
    requires_metadata_only=True,
    notes="Public metadata only; no paywall bypass.",
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

