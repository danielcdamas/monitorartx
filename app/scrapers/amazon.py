"""Scraper da Amazon Brasil.

Extrai os cards da página de busca. A Amazon bloqueia bots com página de
captcha; quando isso acontece o erro é reportado claramente no status.
"""
from __future__ import annotations

import asyncio
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from ..models import Offer
from .base import BaseScraper, is_target_gpu, parse_brl


def _search_url(query: str) -> str:
    return f"https://www.amazon.com.br/s?k={quote_plus(query)}&i=computers"

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

    async def _search(self, query: str) -> list[Offer]:
        html = await self._search_html(_search_url(query))
        # parsing de HTML é pesado — fora do event loop
        return await asyncio.to_thread(self.parse_html, html)

    async def _search_html(self, url: str) -> str:
        # TLS de navegador primeiro: o anti-bot da Amazon detecta o TLS do Python
        resp = await self.impersonated_request("GET", url, headers=_EXTRA_HEADERS)
        if resp is not None:
            if resp.status_code == 200:
                return resp.text
            raise RuntimeError(
                f"Amazon bloqueou a requisição (HTTP {resp.status_code} / anti-bot)."
            )
        async with self.make_client(headers=_EXTRA_HEADERS) as client:
            r = await client.get(url)
            if r.status_code in (403, 503):
                raise RuntimeError(
                    f"Amazon bloqueou a requisição (HTTP {r.status_code} / anti-bot)."
                )
            r.raise_for_status()
            return r.text

    async def diagnose(self) -> dict:
        """Raio-X: status da busca, nº de cards e início do texto da página."""
        try:
            import curl_cffi  # noqa: F401
            transport = "curl_cffi (TLS de navegador)"
        except ImportError:
            transport = "httpx"
        out: dict = {"store": self.store, "url": _search_url("rtx 5080"), "transport": transport}
        try:
            html = await self._search_html(_search_url("rtx 5080"))
            out["status"] = 200
            out["bytes"] = len(html)
            soup = BeautifulSoup(html, "lxml")
            out["result_cards"] = len(
                soup.select('div[data-component-type="s-search-result"][data-asin]')
            )
            out["page_start"] = soup.get_text(" ", strip=True)[:300]
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return out

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
            if not is_target_gpu(name):
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

        return offers
