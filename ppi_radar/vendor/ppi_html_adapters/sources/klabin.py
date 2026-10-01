from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="klabin", source_id="BENCH-0049", source_name="Klabin — Investor Relations",
    endpoint="https://ri.klabin.com.br/", country="Brazil", language="pt",
    item_selectors=("article", ".news-item", ".release-item", ".list-item", "[class*='card']"),
    title_selectors=("h2", "h3", "h4", ".title", "[class*='title']"),
    include_url_patterns=(r"ri\.klabin\.com\.br/", r"api\.mziq\.com/"),
    requires_metadata_only=True,
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

