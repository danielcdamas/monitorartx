"""Scraper da Amazon Brasil.

Extrai os cards da página de busca. A Amazon bloqueia bots com página de
captcha; quando isso acontece o erro é reportado claramente no status.
"""
from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup

from ..models import Offer
from .base import BaseScraper, is_rtx5080_gpu, parse_brl

SEARCH_URL = "https://www.amazon.com.br/s?k=rtx+5080&i=computers"

_EXTRA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

_BLOCK_MARKERS = (
    "api-services-support@amazon.com",
    "Digite os caracteres",
    "captcha",
    "automated access",
)


class AmazonScraper(BaseScraper):
    store = "amazon"
    store_label = "Amazon"

    async def fetch(self) -> list[Offer]:
        async with self.make_client(headers=_EXTRA_HEADERS) as client:
            resp = await client.get(SEARCH_URL)
            if resp.status_code in (403, 503):
                raise RuntimeError(
                    f"Amazon bloqueou a requisição (HTTP {resp.status_code} / anti-bot)."
                )
            resp.raise_for_status()
            # parsing de HTML é pesado — fora do event loop
            return await asyncio.to_thread(self.parse_html, resp.text)

    # ------------------------------------------------------------------ parse

    def parse_html(self, html: str) -> list[Offer]:
        low = html.lower()
        if any(marker.lower() in low for marker in _BLOCK_MARKERS):
            raise RuntimeError("Amazon retornou página de captcha (anti-bot).")

        soup = BeautifulSoup(html, "lxml")
        offers: list[Offer] = []
        seen: set[str] = set()

        for card in soup.select('div[data-component-type="s-search-result"][data-asin]'):
            asin = card.get("data-asin", "").strip()
            if not asin:
                continue

            # pula anúncios patrocinados
            if card.select_one(".puis-sponsored-label-text") or "Patrocinado" in card.get_text():
                continue

            h2 = card.select_one("h2")
            name = h2.get_text(" ", strip=True) if h2 else ""
            if not is_rtx5080_gpu(name):
                continue

            # a-text-price é o preço "de" riscado; o preço real fica em a-price puro
            price_node = card.select_one("span.a-price:not(.a-text-price) > span.a-offscreen")
            price = parse_brl(price_node.get_text(strip=True)) if price_node else None
            available = price is not None and "Indisponível" not in card.get_text()
            if price is None or price < 1000:  # sem preço (indisponível) ou acessório barato
                continue

            url = f"https://www.amazon.com.br/dp/{asin}"
            if url in seen:
                continue
            seen.add(url)
            offers.append(self.offer(name=name, price=price, url=url, available=available))

        if not offers:
            raise RuntimeError("nenhum resultado RTX 5080 extraído da busca da Amazon")
        return offers
