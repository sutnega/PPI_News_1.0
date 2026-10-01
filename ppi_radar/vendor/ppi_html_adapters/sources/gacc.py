from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="gacc", source_id="SRC-0366", source_name="General Administration of Customs China",
    endpoint="https://english.customs.gov.cn/Statistics/Statistics?ColumnId=1", country="China", language="en",
    item_selectors=(".list li", ".news-list li", "article", "table tr", "[class*='list'] li"),
    title_selectors=("h2", "h3", "td a", ".title", "a[title]"),
    link_selectors=("td a[href]", "a[href]"),
    date_selectors=("time", "td.date", ".date", "[class*='date']"),
    include_url_patterns=(r"english\.customs\.gov\.cn/(Statistics|Statics|statics)/",),
    rate_limit_seconds=5.0,
    timeout_seconds=40.0,
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

