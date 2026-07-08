"""Registro dos scrapers de loja."""
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

__all__ = ["BaseScraper", "ALL_SCRAPERS"]
