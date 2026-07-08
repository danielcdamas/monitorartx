"""Scraper da PC Gamer Brasília (https://www.pcgamerbrasilia.com.br/).

A plataforma da loja é desconhecida, então a coleta é agnóstica:
1. procura JSON-LD (application/ld+json) com produtos — padrão em Tray, VTEX,
   Nuvemshop, Loja Integrada, WooCommerce etc.;
2. cai para uma heurística genérica de cards (link de produto + preço próximo).
Vários padrões de URL de busca são tentados até um trazer resultados.
O endpoint /api/diag/pcgamer revela qual URL/estratégia funcionou.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Iterator

from bs4 import BeautifulSoup

from ..models import Offer
from .base import BaseScraper, _normalize, is_rtx5080_gpu, parse_brl

# preço BR sempre tem centavos ("9.199,00") — exige a vírgula para não
# capturar o "5080" do nome do produto como se fosse preço
_PRICE_CENTS_RE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")

BASE = "https://www.pcgamerbrasilia.com.br"
# a loja é WooCommerce (WordPress): a busca de produtos é ?s=...&post_type=product
SEARCH_URLS = [
    f"{BASE}/?s=rtx+5080&post_type=product",
    f"{BASE}/?s=rtx+5080",
    f"{BASE}/?post_type=product&s=rtx%205080",
]
_PRICE_FLOOR = 3000.0
_OUT_OF_STOCK = ("esgotado", "fora de estoque", "indisponivel", "sem estoque")


def _iter_json(obj: Any) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_json(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_json(v)


def _as_price(value: Any) -> float | None:
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    if isinstance(value, str):
        # JSON-LD costuma usar ponto decimal ("9999.90"); parse_brl trata BRL
        try:
            v = float(value.replace(",", "."))
            if v > 0:
                return v
        except ValueError:
            return parse_brl(value)
    return None


class PcGamerBrasiliaScraper(BaseScraper):
    store = "pcgamer"
    store_label = "PC Gamer Brasília"

    async def fetch(self) -> list[Offer]:
        last_error: Exception | None = None
        async with self.make_client() as client:
            for url in SEARCH_URLS:
                try:
                    resp = await client.get(url)
                    if resp.status_code >= 400:
                        continue
                    offers = await asyncio.to_thread(self.parse_html, resp.text)
                    if offers:
                        return offers
                except Exception as exc:
                    last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError("nenhuma RTX 5080 encontrada na PC Gamer Brasília")

    # ------------------------------------------------------------------ parse

    def parse_html(self, html: str) -> list[Offer]:
        for parser in (self._parse_woocommerce, self._parse_jsonld, self._parse_generic):
            offers = parser(html)
            if offers:
                return offers
        return []

    def _parse_woocommerce(self, html: str) -> list[Offer]:
        """Cards padrão do WooCommerce: li.product com .price (ins = promoção)."""
        soup = BeautifulSoup(html, "lxml")
        offers: list[Offer] = []
        seen: set[str] = set()
        for li in soup.select("ul.products li.product, li.product"):
            title_el = li.select_one(
                ".woocommerce-loop-product__title, h2.woocommerce-loop-product__title, h2, h3"
            )
            link_el = li.select_one("a.woocommerce-LoopProduct-link[href], a[href]")
            name = title_el.get_text(" ", strip=True) if title_el else ""
            if not is_rtx5080_gpu(name) and link_el is not None:
                name = (link_el.get("title") or link_el.get_text(" ", strip=True) or "").strip()
            if not is_rtx5080_gpu(name):
                continue

            price_span = li.select_one(".price")
            price = None
            if price_span is not None:
                # preço de venda: <ins> quando em promoção; ignora o <del> riscado
                ins = price_span.select_one("ins")
                target = ins if ins is not None else price_span
                if ins is None:
                    for d in target.select("del"):
                        d.extract()
                amount = target.select_one(".woocommerce-Price-amount, bdi") or target
                price = parse_brl(amount.get_text(" ", strip=True))
            if not price or price < _PRICE_FLOOR:
                continue

            href = (link_el.get("href") if link_el else "") or BASE
            url = href if href.startswith("http") else BASE + ("" if href.startswith("/") else "/") + href
            if url in seen:
                continue
            seen.add(url)
            classes = " ".join(li.get("class", []))
            text = _normalize(li.get_text(" ", strip=True))
            available = "outofstock" not in classes and not any(m in text for m in _OUT_OF_STOCK)
            offers.append(self.offer(name=name, price=price, url=url, available=available))
        return offers

    def _parse_jsonld(self, html: str) -> list[Offer]:
        soup = BeautifulSoup(html, "lxml")
        offers: list[Offer] = []
        seen: set[str] = set()
        for script in soup.select('script[type="application/ld+json"]'):
            raw = script.string or script.get_text()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            for node in _iter_json(data):
                types = node.get("@type")
                is_product = types == "Product" or (isinstance(types, list) and "Product" in types)
                if not is_product:
                    continue
                name = node.get("name")
                if not isinstance(name, str) or not is_rtx5080_gpu(name):
                    continue
                offer_node = node.get("offers")
                offers_list = offer_node if isinstance(offer_node, list) else [offer_node]
                price = None
                available = True
                for off in offers_list:
                    if not isinstance(off, dict):
                        continue
                    price = _as_price(off.get("price") or off.get("lowPrice"))
                    avail = str(off.get("availability") or "")
                    available = "instock" in avail.lower() or "in_stock" in avail.lower() or not avail
                    if price:
                        break
                if not price or price < _PRICE_FLOOR:
                    continue
                url = node.get("url") or node.get("@id") or BASE
                if not isinstance(url, str):
                    url = BASE
                if not url.startswith("http"):
                    url = BASE + ("" if url.startswith("/") else "/") + url
                if url in seen:
                    continue
                seen.add(url)
                offers.append(self.offer(name=name, price=price, url=url, available=available))
        return offers

    def _parse_generic(self, html: str) -> list[Offer]:
        """Fallback: liga cada link de produto RTX 5080 ao preço mais próximo."""
        soup = BeautifulSoup(html, "lxml")
        offers: list[Offer] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            name = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
            if not is_rtx5080_gpu(name):
                continue
            href = a["href"]
            url = href if href.startswith("http") else BASE + ("" if href.startswith("/") else "/") + href
            if url in seen:
                continue
            # sobe alguns níveis procurando um preço (com centavos) no bloco
            node, price = a, None
            for _ in range(4):
                node = node.parent
                if node is None:
                    break
                for m in _PRICE_CENTS_RE.finditer(node.get_text(" ", strip=True)):
                    v = parse_brl(m.group(0))
                    if v and v >= _PRICE_FLOOR:
                        price = v
                        break
                if price:
                    break
            if not price:
                continue
            seen.add(url)
            offers.append(self.offer(name=name, price=price, url=url, available=True))
        return offers

    async def diagnose(self) -> dict:
        out: dict = {"store": self.store, "steps": []}
        async with self.make_client() as client:
            for url in SEARCH_URLS:
                step: dict = {"url": url}
                try:
                    resp = await client.get(url)
                    step["status"] = resp.status_code
                    step["bytes"] = len(resp.text)
                    if resp.status_code < 400:
                        soup = BeautifulSoup(resp.text, "lxml")
                        gen = soup.find("meta", attrs={"name": "generator"})
                        step["generator"] = gen.get("content") if gen else None
                        step["woo_product_lis"] = len(soup.select("li.product"))
                        step["woo_offers"] = len(self._parse_woocommerce(resp.text))
                        step["jsonld_offers"] = len(self._parse_jsonld(resp.text))
                        step["generic_offers"] = len(self._parse_generic(resp.text))
                        step["title"] = soup.title.get_text(strip=True) if soup.title else None
                        sample = []
                        for li in soup.select("li.product")[:4]:
                            t = li.select_one(".woocommerce-loop-product__title, h2, h3")
                            pr = li.select_one(".price")
                            sample.append({
                                "name": (t.get_text(" ", strip=True) if t else "")[:80],
                                "price_text": (pr.get_text(" ", strip=True) if pr else "")[:60],
                            })
                        step["sample"] = sample
                except Exception as exc:
                    step["error"] = f"{type(exc).__name__}: {exc}"[:300]
                out["steps"].append(step)
        return out
