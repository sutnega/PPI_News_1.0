from ..base import ConfiguredHTMLAdapter
from ..config import SourceConfig

CONFIG = SourceConfig(
    slug="appm", source_id="BENCH-0067", source_name="Архангельский ЦБК — пресс-центр",
    endpoint="https://www.appm.ru/press-center/", country="Russia", language="ru",
    item_selectors=("article", ".news-item", ".press-item", "[class*='news']", "[class*='press'] li"),
    title_selectors=("h2", "h3", ".news-title", "[class*='title']"),
    include_url_patterns=(r"appm\.ru/press-center/",),
)

class Adapter(ConfiguredHTMLAdapter):
    CONFIG = CONFIG

