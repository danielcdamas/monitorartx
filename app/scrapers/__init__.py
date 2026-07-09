"""Registro dos scrapers de loja."""
import os

from .base import BaseScraper
from .terabyte import TerabyteScraper
from .kabum import KabumScraper
from .pichau import PichauScraper
from .amazon import AmazonScraper
from .mercadolivre import MercadoLivreScraper
from .pcgamerbrasilia import PcGamerBrasiliaScraper

ALL_SCRAPERS: list[type[BaseScraper]] = [
    TerabyteScraper,
    KabumScraper,
    PichauScraper,
    AmazonScraper,
    MercadoLivreScraper,
    PcGamerBrasiliaScraper,
]


def select_scrapers() -> list[BaseScraper]:
    """Lojas ativas no monitoramento.

    - MONITOR_STORES (ex.: "terabyte,kabum,amazon") força uma lista explícita.
    - Sem ela: inclui as lojas default_enabled; as que requires_proxy só
      entram se houver SCRAPER_PROXY configurado (senão sumiriam do painel
      apenas com erro). PC Gamer (SPA) fica fora até ser pedida explicitamente.
    """
    instances = [cls() for cls in ALL_SCRAPERS]
    env = os.environ.get("MONITOR_STORES", "").strip()
    if env:
        wanted = {s.strip().lower() for s in env.split(",") if s.strip()}
        return [s for s in instances if s.store in wanted]
    active = []
    for s in instances:
        if not s.default_enabled:
            continue
        if s.requires_proxy and not s.proxy:
            continue
        active.append(s)
    return active


__all__ = ["BaseScraper", "ALL_SCRAPERS", "select_scrapers"]
