"""Scraper da Terabyteshop.

O site não expõe API pública; extraímos os cards de produto do HTML da busca
(e da categoria RTX série 50 como fallback). A Terabyteshop usa WAF agressivo:
se a resposta vier bloqueada, o erro é reportado com orientação.
"""
from __future__ import annotations

import asyncio
import re

from bs4 import BeautifulSoup

from ..models import Offer
from .base import BaseScraper, _normalize, is_rtx5080_gpu, parse_brl

SEARCH_URL = "https://www.terabyteshop.com.br/busca?str=rtx+5080"
CATEGORY_URL = "https://www.terabyteshop.com.br/hardware/placas-de-video/nvidia/geforce-rtx-serie-5000"

# "12x de R$ 700,00" ou "12x R$ 991,66" — valor de parcela, não é preço:
# numa placa cara a parcela passa de R$ 1.000 e enganaria o filtro de piso
_INSTALLMENT_RE = re.compile(r"\d+\s*x\s*(?:de\s*)?$", re.IGNORECASE)
_PRICE_RE = re.compile(r"R\$\s*([\d\.]+,\d{2})")

# marcadores de "sem estoque" no texto do card (comparados sem acentos)
_UNAVAILABLE_MARKERS = (
    "indispon", "avise-me", "avise me", "sob consulta",
    "esgotado", "sem estoque", "notifique",
)


class TerabyteScraper(BaseScraper):
    store = "terabyte"
    store_label = "Terabyteshop"

    async def fetch(self) -> list[Offer]:
        async with self.make_client() as client:
            last_error: Exception | None = None
            for url in (SEARCH_URL, CATEGORY_URL):
                try:
                    resp = await client.get(url)
                    if resp.status_code in (403, 503):
                        raise RuntimeError(
                            f"Terabyteshop bloqueou a requisição (HTTP {resp.status_code}). "
                            "O WAF deles costuma barrar IPs de datacenter — rode em rede residencial."
                        )
                    resp.raise_for_status()
                    # parsing de HTML é pesado — fora do event loop
                    offers = await asyncio.to_thread(self.parse_html, resp.text)
                    if offers:
                        return offers
                except Exception as exc:
                    last_error = exc
            if last_error:
                raise last_error
            raise RuntimeError("nenhum produto RTX 5080 encontrado na Terabyteshop")

    # ------------------------------------------------------------------ parse

    def parse_html(self, html: str) -> list[Offer]:
        soup = BeautifulSoup(html, "lxml")
        offers: list[Offer] = []
        seen: set[str] = set()

        # âncoras de produto são o ponto estável; o card é um ancestral próximo
        for a in soup.select('a[href*="/produto/"]'):
            href = a.get("href") or ""
            if not re.search(r"/produto/\d+", href):
                continue
            url = href if href.startswith("http") else f"https://www.terabyteshop.com.br{href}"
            if url in seen:
                continue

            name = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
            if not is_rtx5080_gpu(name):
                continue

            card = self._climb(a)
            price, price_card = self._extract_prices(card)
            unavailable = self._is_unavailable(card)
            if price is None:
                continue  # sem preço: nada para monitorar

            seen.add(url)
            offers.append(self.offer(
                name=name,
                price=price,
                price_card=price_card,
                url=url,
                available=not unavailable,
            ))
        return offers

    def _climb(self, a):
        """Sobe do link do produto até o card, sem invadir cards vizinhos."""
        card = a
        for _ in range(5):
            parent = card.parent
            if parent is None:
                break
            # não sobe para um ancestral com outros produtos: um card sem
            # preço (esgotado) absorveria o preço do card vizinho
            hrefs = {p.get("href") or "" for p in parent.select('a[href*="/produto/"]')}
            if len(hrefs) > 1:
                break
            card = parent
            if _PRICE_RE.search(card.get_text(" ", strip=True)):
                break
        return card

    def _is_unavailable(self, card) -> bool:
        text = _normalize(card.get_text(" ", strip=True))
        return any(m in text for m in _UNAVAILABLE_MARKERS)

    async def diagnose(self) -> dict:
        """Raio-X do que a loja devolve: status HTTP, título e amostra dos cards."""
        out: dict = {"store": self.store, "steps": []}
        async with self.make_client() as client:
            for url in (SEARCH_URL, CATEGORY_URL):
                step: dict = {"url": url}
                try:
                    resp = await client.get(url)
                    step["status"] = resp.status_code
                    step["bytes"] = len(resp.text)
                    soup = BeautifulSoup(resp.text, "lxml")
                    step["title"] = soup.title.get_text(strip=True) if soup.title else None
                    cards, seen = [], set()
                    for a in soup.select('a[href*="/produto/"]'):
                        href = a.get("href") or ""
                        if not re.search(r"/produto/\d+", href) or href in seen:
                            continue
                        seen.add(href)
                        name = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
                        if not name:
                            continue
                        card = self._climb(a)
                        price, price_card = self._extract_prices(card)
                        cards.append({
                            "name": name[:90],
                            "is_rtx5080": is_rtx5080_gpu(name),
                            "price": price,
                            "price_card": price_card,
                            "unavailable_marker": self._is_unavailable(card),
                            "card_text": card.get_text(" ", strip=True)[:400],
                        })
                        if len(cards) >= 6:
                            break
                    step["cards"] = cards
                except Exception as exc:
                    step["error"] = f"{type(exc).__name__}: {exc}"[:300]
                out["steps"].append(step)
        return out

    def _extract_prices(self, card) -> tuple[float | None, float | None]:
        """(preço à vista/pix, preço no cartão) a partir do card do produto."""
        # 1) classes conhecidas do layout
        node = card.select_one(".prod-new-price span, .prod-new-price, .product-item__new-price")
        pix = parse_brl(node.get_text(" ", strip=True)) if node else None

        text = card.get_text(" ", strip=True)
        prices: list[float] = []
        for m in _PRICE_RE.finditer(text):
            before = text[max(0, m.start() - 12):m.start()]
            if _INSTALLMENT_RE.search(before):
                continue  # é valor de parcela
            v = parse_brl(m.group(0))
            if v and v >= 1000:  # placa de vídeo: ignora acessórios/ruído
                prices.append(v)

        if pix is None and prices:
            pix = min(prices)
        card_price = None
        if pix is not None:
            higher = [p for p in prices if p > pix]
            if higher:
                card_price = min(higher)
        return pix, card_price
