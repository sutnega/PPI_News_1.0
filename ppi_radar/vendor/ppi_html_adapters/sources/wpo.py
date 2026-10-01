from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="wpo", source_id="NEW-0027", source_name="World Packaging Organisation (WPO)",
    endpoint="https://www.worldpackaging.org/wpo/1/", country="World", language="en",
    item_selectors=("article", ".news-item", ".content-item", ".card", "[class*='news']"),
    include_url_patterns=(r"worldpackaging\.org/wpo/",),
    exclude_url_patterns=SourceConfig.__dataclass_fields__["exclude_url_patterns"].default + (r"/wpo/1/?$",),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

