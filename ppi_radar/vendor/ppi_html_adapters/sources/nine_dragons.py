from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="nine-dragons", source_id="NEW-0053", source_name="Nine Dragons Paper",
    endpoint="https://www.ndpaper.com/en/ir/announcements.php", country="China", language="en",
    item_selectors=(".announcement-list li", ".news-list li", "article", "table tr", "[class*='announcement']"),
    title_selectors=("h2", "h3", "td a", ".title", "a[title]"),
    link_selectors=("td a[href]", "a[href]"),
    date_selectors=("time", "td.date", ".date", "[class*='date']"),
    include_url_patterns=(r"ndpaper\.com/en/", r"doc\.irasia\.com/"),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

