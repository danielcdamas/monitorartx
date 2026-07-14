"""Scraper da KaBuM!

Estratégia primária: API pública de catálogo usada pelo próprio frontend.
Fallback: JSON embutido (__NEXT_DATA__) da página de busca.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator
from urllib.parse import quote

from ..models import Offer
from .base import BaseScraper, is_target_gpu


def _api_url(query: str) -> str:
    return (
        "https://servicespub.prod.api.aws.grupokabum.com.br/catalogo/v2/products"
        f"?query={quote(query)}&page_number=1&page_size=100"
    )


def _search_url(query: str) -> str:
    return f"https://www.kabum.com.br/busca/{query.replace(' ', '-')}"


def _iter_dicts(obj: Any) -> Iterator[dict]:
    """Percorre recursivamente uma estrutura JSON e produz todos os dicts."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dicts(v)


def _first_number(d: dict, *keys: str) -> float | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


class KabumScraper(BaseScraper):
    store = "kabum"
    store_label = "KaBuM!"

    async def _search(self, query: str) -> list[Offer]:
        async with self.make_client(headers={"Accept": "application/json, text/plain, */*"}) as client:
            primary_err: Exception | None = None
            try:
                resp = await client.get(_api_url(query))
                resp.raise_for_status()
                offers = self.parse_api(resp.json())
                if offers:
                    return offers
            except Exception as exc:
                primary_err = exc  # tenta o fallback pela página de busca

            try:
                resp = await client.get(_search_url(query))
                resp.raise_for_status()
                return self.parse_search_html(resp.text)
            except Exception as exc:
                if primary_err is not None:
                    # o status só mostra str(exc): inclui as duas causas
                    raise RuntimeError(
                        f"API: {type(primary_err).__name__}: {primary_err}; "
                        f"busca: {type(exc).__name__}: {exc}"
                    ) from exc
                raise

    async def diagnose(self) -> dict:
        """Raio-X: status e formato do que a API e a página de busca devolvem."""
        out: dict = {"store": self.store, "steps": []}
        async with self.make_client(headers={"Accept": "application/json, text/plain, */*"}) as client:
            step: dict = {"url": _api_url("rtx 5080")}
            try:
                resp = await client.get(_api_url("rtx 5080"))
                step["status"] = resp.status_code
                step["bytes"] = len(resp.text)
                try:
                    data = resp.json()
                    step["json_keys"] = sorted(data)[:10] if isinstance(data, dict) else type(data).__name__
                    step["parsed_offers"] = len(self.parse_api(data))
                except Exception:
                    step["body_start"] = resp.text[:300]
            except Exception as exc:
                step["error"] = f"{type(exc).__name__}: {exc}"[:300]
            out["steps"].append(step)

            step = {"url": _search_url("rtx 5080")}
            try:
                resp = await client.get(_search_url("rtx 5080"))
                step["status"] = resp.status_code
                step["bytes"] = len(resp.text)
                step["has_next_data"] = 'id="__NEXT_DATA__"' in resp.text
                try:
                    step["parsed_offers"] = len(self.parse_search_html(resp.text))
                except Exception as exc:
                    step["parse_error"] = str(exc)[:200]
            except Exception as exc:
                step["error"] = f"{type(exc).__name__}: {exc}"[:300]
            out["steps"].append(step)
        return out

    # ------------------------------------------------------------------ parse

    def parse_api(self, data: Any) -> list[Offer]:
        """Extrai ofertas do JSON da API de catálogo (formato JSON:API)."""
        offers: list[Offer] = []
        seen: set[str] = set()
        for item in _iter_dicts(data):
            attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
            name = attrs.get("title") or attrs.get("name")
            if not isinstance(name, str) or not is_target_gpu(name):
                continue
            price_pix = _first_number(
                attrs, "price_with_discount", "priceWithDiscount", "price_discount", "priceDiscount"
            )
            price_card = _first_number(attrs, "price", "price_marketplace", "priceMarketplace")
            best = price_pix or price_card
            if not best:
                continue
            code = item.get("id") or attrs.get("code") or attrs.get("id")
            if not code:
                continue
            url = f"https://www.kabum.com.br/produto/{code}"
            if url in seen:
                continue
            seen.add(url)
            available = attrs.get("available")
            offers.append(self.offer(
                name=name,
                price=best,
                price_card=price_card if price_pix and price_card and price_card > price_pix else None,
                url=url,
                available=bool(available) if available is not None else True,
            ))
        return offers

    def parse_search_html(self, html: str) -> list[Offer]:
        """Fallback: extrai produtos do __NEXT_DATA__ da página de busca."""
        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
        )
        if not m:
            raise RuntimeError("página da KaBuM sem __NEXT_DATA__ (possível bloqueio anti-bot)")
        data = json.loads(m.group(1))
        offers: list[Offer] = []
        seen: set[str] = set()
        for d in _iter_dicts(data):
            name = d.get("name") or d.get("title")
            if not isinstance(name, str) or not is_target_gpu(name):
                continue
            price_pix = _first_number(d, "priceWithDiscount", "price_with_discount", "priceDiscount")
            price_card = _first_number(d, "price", "priceMarketplace")
            best = price_pix or price_card
            code = d.get("code") or d.get("id")
            if not best or not code:
                continue
            url = f"https://www.kabum.com.br/produto/{code}"
            if url in seen:
                continue
            seen.add(url)
            available = d.get("available")
            offers.append(self.offer(
                name=name,
                price=best,
                price_card=price_card if price_pix and price_card and price_card > price_pix else None,
                url=url,
                available=bool(available) if available is not None else True,
            ))
        return offers
