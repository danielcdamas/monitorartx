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
# WooCommerce: a página de busca carrega produtos via JS, mas a Store API
# (pública, sem auth) devolve os produtos em JSON — é a via confiável.
STORE_API_URLS = [
    f"{BASE}/wp-json/wc/store/v1/products?search=rtx%205080&per_page=50",
    f"{BASE}/wp-json/wc/store/products?search=rtx%205080&per_page=50",
]
# fallback: busca HTML (WordPress ?s=...)
SEARCH_URLS = [
    f"{BASE}/?s=rtx+5080&post_type=product",
    f"{BASE}/?s=rtx+5080",
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
    # storefront em JavaScript (SPA): produtos não vêm no HTML e não há API
    # pública acessível — sem coleta viável por HTTP, fora do padrão
    default_enabled = False

    async def _get(self, url: str, *, json_accept: bool = False) -> tuple[int, str]:
        """GET com TLS de navegador (curl_cffi) e fallback httpx.

        O WAF da loja derruba conexões não-navegador na Store API, então o
        handshake de Chrome é o que faz a API responder.
        """
        headers = {"Accept": "application/json"} if json_accept else {}
        resp = await self.impersonated_request("GET", url, headers=headers)
        if resp is not None:
            return resp.status_code, resp.text
        async with self.make_client(headers=headers) as client:
            r = await client.get(url)
            return r.status_code, r.text

    async def fetch(self) -> list[Offer]:
        last_error: Exception | None = None
        # 1) Store API do WooCommerce (JSON, TLS de navegador contra o WAF)
        for api in STORE_API_URLS:
            try:
                status, text = await self._get(api, json_accept=True)
                if status >= 400:
                    continue
                offers = self._parse_store_api(json.loads(text))
                if offers:
                    return offers
            except Exception as exc:
                last_error = exc
        # 2) fallback: HTML da busca
        for url in SEARCH_URLS:
            try:
                status, text = await self._get(url)
                if status >= 400:
                    continue
                offers = await asyncio.to_thread(self.parse_html, text)
                if offers:
                    return offers
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError("nenhuma RTX 5080 encontrada na PC Gamer Brasília")

    def _parse_store_api(self, data: Any) -> list[Offer]:
        """Produtos da WooCommerce Store API (preços em unidades menores)."""
        if not isinstance(data, list):
            return []
        offers: list[Offer] = []
        seen: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not is_rtx5080_gpu(name):
                continue
            prices = item.get("prices") or {}
            raw = prices.get("price") or prices.get("sale_price") or prices.get("regular_price")
            minor = prices.get("currency_minor_unit", 2)
            try:
                price = int(raw) / (10 ** int(minor))
            except (TypeError, ValueError):
                continue
            if price < _PRICE_FLOOR:
                continue
            url = item.get("permalink") or BASE
            if url in seen:
                continue
            seen.add(url)
            available = bool(item.get("is_in_stock", True))
            offers.append(self.offer(name=name, price=price, url=url, available=available))
        return offers

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
        try:
            import curl_cffi  # noqa: F401
            transport = "curl_cffi (TLS de navegador)"
        except ImportError:
            transport = "httpx"
        out: dict = {"store": self.store, "transport": transport, "steps": []}
        # sonda a Store API primeiro
        for api in STORE_API_URLS:
            step: dict = {"url": api, "kind": "store-api"}
            try:
                status, text = await self._get(api, json_accept=True)
                step["status"] = status
                step["bytes"] = len(text)
                if status < 400:
                    try:
                        data = json.loads(text)
                        step["items"] = len(data) if isinstance(data, list) else "não-lista"
                        step["parsed_offers"] = len(self._parse_store_api(data))
                        if isinstance(data, list) and data:
                            names = [d.get("name", "")[:70] for d in data[:5] if isinstance(d, dict)]
                            step["names"] = names
                    except Exception:
                        step["body_start"] = text[:200]
            except Exception as exc:
                step["error"] = f"{type(exc).__name__}: {exc}"[:300]
            out["steps"].append(step)
        for url in SEARCH_URLS:
            step = {"url": url}
            try:
                status, text = await self._get(url)
                step["status"] = status
                step["bytes"] = len(text)
                if status < 400:
                    soup = BeautifulSoup(text, "lxml")
                    gen = soup.find("meta", attrs={"name": "generator"})
                    step["generator"] = gen.get("content") if gen else None
                    step["woo_product_lis"] = len(soup.select("li.product"))
                    step["woo_offers"] = len(self._parse_woocommerce(text))
                    step["jsonld_offers"] = len(self._parse_jsonld(text))
                    step["generic_offers"] = len(self._parse_generic(text))
                    step["title"] = soup.title.get_text(strip=True) if soup.title else None
                    # revela links de produto e menções a 5080 se nada casou
                    prod_links = [a.get("href") for a in soup.find_all("a", href=True)
                                  if "produto" in (a.get("href") or "")][:5]
                    step["produto_links"] = prod_links
                    step["conta_5080"] = text.lower().count("5080")
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
