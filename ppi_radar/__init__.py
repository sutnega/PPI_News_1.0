"""PPI Radar standalone HTML adapters."""

from .models import ArticleItem, RunReport
from .registry import create_adapter, list_sources

__all__ = ["ArticleItem", "RunReport", "create_adapter", "list_sources"]
__version__ = "0.1.0"

