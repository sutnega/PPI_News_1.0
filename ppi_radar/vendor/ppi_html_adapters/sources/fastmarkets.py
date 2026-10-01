from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="fastmarkets", source_id="SRC-0030", source_name="Fastmarkets Forest Products",
    endpoint="https://www.fastmarkets.com/forest-products/pulp/", country="World", language="en",
    item_selectors=("article", "[data-testid*='card']", "[class*='Card']", ".listing-item"),
    title_selectors=("h2", "h3", "[class*='title']"),
    include_url_patterns=(r"fastmarkets\.com/(insights|forest-products)/",),
    requires_metadata_only=True,
    notes="Public metadata only; paid articles remain linked, not bypassed.",
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

