"""Scraper da Pichau.

Estratégia primária: endpoint GraphQL (Magento 2) usado pelo próprio site,
pedindo apenas campos padrão do schema de products.
Fallback: JSON embutido (__NEXT_DATA__) da página de busca.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator

from ..models import Offer
from .base import BaseScraper, is_rtx5080_gpu

GRAPHQL_URL = "https://www.pichau.com.br/api/pichau"
SEARCH_URL = "https://www.pichau.com.br/search?q=rtx%205080"

GRAPHQL_QUERY = """
query {
  products(search: "rtx 5080", pageSize: 60, currentPage: 1) {
    total_count
    items {
      sku
      name
      url_key
      stock_status
      special_price
      price_range {
        minimum_price {
          regular_price { value }
          final_price { value }
        }
      }
    }
  }
}
"""


def _iter_dicts(obj: Any) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dicts(v)


class PichauScraper(BaseScraper):
    store = "pichau"
    store_label = "Pichau"

    async def fetch(self) -> list[Offer]:
        async with self.make_client() as client:
            primary_err: Exception | None = None
            try:
                resp = await client.post(
                    GRAPHQL_URL,
                    json={"query": GRAPHQL_QUERY},
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                resp.raise_for_status()
                offers = self.parse_graphql(resp.json())
                if offers:
                    return offers
            except Exception as exc:
                primary_err = exc  # tenta o fallback pela página de busca

            try:
                resp = await client.get(SEARCH_URL)
                resp.raise_for_status()
                return self.parse_search_html(resp.text)
            except Exception as exc:
                if primary_err is not None:
                    # o status só mostra str(exc): inclui as duas causas
                    raise RuntimeError(
                        f"GraphQL: {type(primary_err).__name__}: {primary_err}; "
                        f"busca: {type(exc).__name__}: {exc}"
                    ) from exc
                raise

    async def diagnose(self) -> dict:
        """Raio-X: o que o GraphQL e a página de busca devolvem."""
        out: dict = {"store": self.store, "steps": []}
        async with self.make_client() as client:
            step: dict = {"url": GRAPHQL_URL, "method": "POST"}
            try:
                resp = await client.post(
                    GRAPHQL_URL,
                    json={"query": GRAPHQL_QUERY},
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                step["status"] = resp.status_code
                step["bytes"] = len(resp.text)
                try:
                    data = resp.json()
                    step["graphql_errors"] = data.get("errors")
                    step["parsed_offers"] = len(self.parse_graphql(data)) if not data.get("errors") else 0
                except Exception:
                    step["body_start"] = resp.text[:300]
            except Exception as exc:
                step["error"] = f"{type(exc).__name__}: {exc}"[:300]
            out["steps"].append(step)

            step = {"url": SEARCH_URL}
            try:
                resp = await client.get(SEARCH_URL)
                step["status"] = resp.status_code
                step["bytes"] = len(resp.text)
                step["has_next_data"] = 'id="__NEXT_DATA__"' in resp.text
                step["body_start"] = resp.text[:200] if resp.status_code != 200 else None
            except Exception as exc:
                step["error"] = f"{type(exc).__name__}: {exc}"[:300]
            out["steps"].append(step)
        return out

    # ------------------------------------------------------------------ parse

    def _offer_from_item(self, item: dict) -> Offer | None:
        name = item.get("name")
        if not isinstance(name, str) or not is_rtx5080_gpu(name):
            return None
        url_key = item.get("url_key")
        if not url_key:
            return None

        final = regular = None
        pr = item.get("price_range") or {}
        minimum = pr.get("minimum_price") or {}
        if isinstance(minimum, dict):
            final = ((minimum.get("final_price") or {}).get("value"))
            regular = ((minimum.get("regular_price") or {}).get("value"))
        special = item.get("special_price")

        candidates = [v for v in (special, final) if isinstance(v, (int, float)) and v > 0]
        if not candidates:
            return None
        price = min(candidates)
        price_card = regular if isinstance(regular, (int, float)) and regular > price else None

        stock = item.get("stock_status")
        available = (stock == "IN_STOCK") if isinstance(stock, str) else True
        return self.offer(
            name=name,
            price=price,
            price_card=price_card,
            url=f"https://www.pichau.com.br/{url_key}",
            available=available,
        )

    def parse_graphql(self, data: dict) -> list[Offer]:
        if data.get("errors"):
            raise RuntimeError(f"GraphQL da Pichau retornou erro: {data['errors'][:1]}")
        items = (((data.get("data") or {}).get("products") or {}).get("items")) or []
        offers = []
        for item in items:
            o = self._offer_from_item(item)
            if o:
                offers.append(o)
        return offers

    def parse_search_html(self, html: str) -> list[Offer]:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            raise RuntimeError("página da Pichau sem __NEXT_DATA__ (possível bloqueio anti-bot)")
        data = json.loads(m.group(1))
        offers: list[Offer] = []
        seen: set[str] = set()
        for d in _iter_dicts(data):
            if "url_key" not in d or "name" not in d:
                continue
            o = self._offer_from_item(d)
            if o and o.url not in seen:
                seen.add(o.url)
                offers.append(o)
        if not offers:
            raise RuntimeError("nenhum produto RTX 5080 encontrado no HTML da Pichau")
        return offers
