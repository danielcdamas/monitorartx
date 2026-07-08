"""Scrapers simulados (modo demo / testes de ponta a ponta).

Ative com MOCK_STORES=1. Gera ofertas plausíveis de RTX 5080 cujos preços
fazem um passeio aleatório entre os ciclos — útil para demonstrar o app sem
depender da rede e para testar UI, SSE, banco e gráfico.
"""
from __future__ import annotations

import random

from ..models import Offer
from .base import BaseScraper

_CATALOG = {
    "terabyte": ("Terabyteshop", [
        ("GeForce RTX 5080 ASUS TUF Gaming OC 16GB GDDR7", 9899.90),
        ("GeForce RTX 5080 Gigabyte Windforce 16GB GDDR7", 9299.90),
        ("GeForce RTX 5080 MSI Gaming Trio 16GB GDDR7", 9599.90),
    ]),
    "kabum": ("KaBuM!", [
        ("Placa de Vídeo RTX 5080 Galax 1-Click OC 16GB GDDR7", 9199.99),
        ("Placa de Vídeo RTX 5080 ASUS Prime OC 16GB GDDR7", 9449.99),
        ("Placa de Vídeo RTX 5080 Zotac Solid 16GB GDDR7", 9099.99),
    ]),
    "pichau": ("Pichau", [
        ("Placa de Video Colorful iGame RTX 5080 Advanced OC 16GB", 9049.90),
        ("Placa de Video Gigabyte RTX 5080 Gaming OC 16GB GDDR7", 9399.90),
    ]),
    "amazon": ("Amazon", [
        ("PNY GeForce RTX 5080 16GB GDDR7 Triple Fan", 9799.00),
        ("MSI GeForce RTX 5080 Ventus 3X OC 16GB GDDR7", 9699.00),
    ]),
}

_state: dict[str, float] = {}  # url -> preço atual (evolui entre ciclos)


class _MockScraper(BaseScraper):
    def __init__(self, store: str, label: str, products: list[tuple[str, float]]) -> None:
        self.store = store
        self.store_label = label
        self._products = products

    async def fetch(self) -> list[Offer]:
        rng = random.Random()
        offers = []
        for i, (name, base) in enumerate(self._products):
            url = f"https://exemplo.dev/{self.store}/rtx-5080-{i}"
            price = _state.get(url, base)
            price = max(base * 0.85, min(base * 1.1, price + rng.uniform(-120, 110)))
            _state[url] = price
            offers.append(self.offer(
                name=f"{name} (simulado)",
                price=round(price, 2),
                price_card=round(price * 1.12, 2),
                url=url,
                available=rng.random() > 0.08,
            ))
        return offers


def build_mock_scrapers() -> list[BaseScraper]:
    return [_MockScraper(store, label, prods) for store, (label, prods) in _CATALOG.items()]
