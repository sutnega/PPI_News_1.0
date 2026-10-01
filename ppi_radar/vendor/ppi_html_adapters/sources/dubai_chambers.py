from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="dubai-chambers", source_id="NEW-0051",
    source_name="Dubai Chamber — Paper, Tissue & Stationery Business Group",
    endpoint="https://www.dubaichambers.com/en/web/dubai-chamber-of-commerce-1/business-groups-business-councils-listing",
    country="UAE", language="en",
    item_selectors=("article", ".card", ".journal-content-article", "[class*='news']", "[class*='content-card']"),
    title_selectors=("h2", "h3", "h4", ".card-title", "[class*='title']"),
    include_url_patterns=(r"dubaichambers\.com/en/w/", r"dubaichambers\.com/en/web/"),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

