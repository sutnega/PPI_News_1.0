from __future__ import annotations

from importlib import import_module

from .base import ConfiguredHTMLAdapter
from .config import SourceConfig

MODULES = {
    "fastmarkets": "fastmarkets",
    "hawkinswright": "hawkinswright",
    "paperfirst": "paperfirst",
    "wpo": "wpo",
    "caixin": "caixin",
    "cppmp": "cppmp",
    "segezha": "segezha",
    "appm": "appm",
    "fsc": "fsc",
    "klabin": "klabin",
    "thenational": "thenational",
    "irna": "irna",
    "iranprint": "iranprint",
    "ft": "ft",
    "pmmi": "pmmi",
    "dubai-chambers": "dubai_chambers",
    "ecba": "ecba",
    "gacc": "gacc",
    "nine-dragons": "nine_dragons",
    "lee-man": "lee_man",
    "app-china": "app_china",
}


def get_adapter_class(slug: str) -> type[ConfiguredHTMLAdapter]:
    try:
        module_name = MODULES[slug]
    except KeyError as exc:
        raise KeyError(f"Unknown source {slug!r}. Use list_sources().") from exc
    module = import_module(f".sources.{module_name}", package=__package__)
    return module.Adapter


def get_config(slug: str) -> SourceConfig:
    return get_adapter_class(slug).CONFIG


def create_adapter(slug: str, **kwargs: object) -> ConfiguredHTMLAdapter:
    return get_adapter_class(slug)(**kwargs)


def list_sources() -> list[SourceConfig]:
    return [get_config(slug) for slug in MODULES]

