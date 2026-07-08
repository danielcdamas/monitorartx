"""Scraper do Mercado Livre.

Marketplace: a busca traz muito ruído (usados, acessórios, anúncios). Além do
filtro padrão de RTX 5080, exclui itens usados e aplica um piso de preço para
descartar acessórios. Usa TLS de navegador (curl_cffi) porque o ML costuma
barrar clientes não-navegador; cai para httpx puro se a lib faltar.
"""
from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup

from ..models import Offer
from .base import BaseScraper, _normalize, is_rtx5080_gpu, parse_brl

SEARCH_URL = "https://lista.mercadolivre.com.br/rtx-5080"

# uma RTX 5080 nova custa muitos milhares — abaixo disso é acessório/erro
_PRICE_FLOOR = 3000.0
# ruído específico de marketplace, além dos termos globais de base.py
_EXTRA_EXCLUDE = ("usado", "seminovo", "cooler", "ventoinha", "somente a caixa",
                  "apenas a caixa", "so a caixa", "pelicula", "chaveiro", "poster")


class MercadoLivreScraper(BaseScraper):
    store = "mercadolivre"
    store_label = "Mercado Livre"

    async def fetch(self) -> list[Offer]:
        html = await self._search_html()
        return await asyncio.to_thread(self.parse_html, html)

    async def _search_html(self) -> str:
        resp = await self.impersonated_request("GET", SEARCH_URL)
        if resp is not None:
            if resp.status_code == 200:
                return resp.text
            raise RuntimeError(f"Mercado Livre respondeu HTTP {resp.status_code} (anti-bot).")
        async with self.make_client() as client:
            r = await client.get(SEARCH_URL)
            r.raise_for_status()
            return r.text

    # ------------------------------------------------------------------ parse

    @staticmethod
    def _money(el) -> float | None:
        """Extrai o valor de um bloco .andes-money-amount (fração + centavos)."""
        if el is None:
            return None
        frac = el.select_one(".andes-money-amount__fraction")
        if not frac:
            return parse_brl(el.get_text(" ", strip=True))
        text = frac.get_text(strip=True)
        cents = el.select_one(".andes-money-amount__cents")
        if cents:
            text += "," + cents.get_text(strip=True)
        return parse_brl(text)

    def parse_html(self, html: str) -> list[Offer]:
        soup = BeautifulSoup(html, "lxml")
        offers: list[Offer] = []
        seen: set[str] = set()

        cards = soup.select("li.ui-search-layout__item") or soup.select("div.poly-card")
        for card in cards:
            title_el = card.select_one(
                ".poly-component__title, .ui-search-item__title, h2.ui-search-item__title, "
                "h3.poly-component__title-wrapper a"
            )
            if not title_el:
                continue
            name = title_el.get_text(" ", strip=True)
            if not is_rtx5080_gpu(name):
                continue
            norm = _normalize(card.get_text(" ", strip=True))
            if any(term in norm for term in _EXTRA_EXCLUDE):
                continue

            # preço vigente: ignora o valor "de" riscado (--previous), que
            # aparece antes no DOM dentro do mesmo contêiner de preço
            price_el = (
                card.select_one(".poly-price__current .andes-money-amount:not(.andes-money-amount--previous)")
                or card.select_one(".ui-search-price__second-line .andes-money-amount:not(.andes-money-amount--previous)")
                or card.select_one(".andes-money-amount:not(.andes-money-amount--previous)")
            )
            price = self._money(price_el)
            if price is None or price < _PRICE_FLOOR:
                continue

            link_el = title_el if title_el.name == "a" else card.select_one(
                "a.poly-component__title, a.ui-search-link, a.ui-search-item__group__element, a[href]"
            )
            href = (link_el.get("href") if link_el else "") or ""
            if not href.startswith("http"):
                continue
            url = href.split("#")[0]
            key = url.split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            offers.append(self.offer(name=name, price=price, url=url, available=True))

        if not offers:
            raise RuntimeError("nenhuma RTX 5080 extraída da busca do Mercado Livre")
        return offers

    async def diagnose(self) -> dict:
        try:
            import curl_cffi  # noqa: F401
            transport = "curl_cffi (TLS de navegador)"
        except ImportError:
            transport = "httpx"
        out: dict = {"store": self.store, "url": SEARCH_URL, "transport": transport}
        try:
            html = await self._search_html()
            out["status"] = 200
            out["bytes"] = len(html)
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("li.ui-search-layout__item") or soup.select("div.poly-card")
            out["result_cards"] = len(cards)
            out["title"] = soup.title.get_text(strip=True) if soup.title else None
            # quando 0 cards: revela se veio página de bloqueio/JS challenge
            low = html.lower()
            markers = [m for m in ("robot", "captcha", "antes de continuar",
                                   "just a moment", "verificando", "cloudflare",
                                   "nenhum resultado", "não encontramos")
                       if m in low]
            out["markers"] = markers
            if not cards:
                out["body_start"] = " ".join(soup.get_text(" ", strip=True).split())[:400]
            sample = []
            for card in cards[:8]:
                t = card.select_one(".poly-component__title, .ui-search-item__title")
                nm = t.get_text(" ", strip=True) if t else None
                price_el = (
                    card.select_one(".poly-price__current .andes-money-amount:not(.andes-money-amount--previous)")
                    or card.select_one(".andes-money-amount:not(.andes-money-amount--previous)")
                )
                sample.append({"name": (nm or "")[:80],
                               "is_rtx5080": is_rtx5080_gpu(nm or ""),
                               "price": self._money(price_el)})
            out["sample"] = sample
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return out
