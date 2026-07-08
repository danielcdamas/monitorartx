"""Infraestrutura comum dos scrapers: HTTP, parse de preço BRL e filtro de produto."""
from __future__ import annotations

import asyncio
import os
import re
import unicodedata
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx


from ..models import Offer

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Termos que indicam que o item NÃO é uma placa de vídeo RTX 5080 avulsa.
_EXCLUDE_TERMS = [
    "water block", "waterblock", "bloco de agua", "block acetal",
    "suporte", "bracket", "cabo", "adaptador", "backplate",
    "pc gamer", "computador", "desktop", "notebook", "laptop",
    "workstation", "monitor", "gabinete", "fonte", "kit upgrade",
    "mochila", "camiseta", "mousepad",
]

_RTX5080_RE = re.compile(r"(rtx\s*5080|5080)", re.IGNORECASE)


def _normalize(text: str) -> str:
    # ™/® antes do NFKD: senão "RTX™" vira "rtxtm" e o regex não casa
    text = text.replace("™", " ").replace("®", " ")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def is_rtx5080_gpu(name: str) -> bool:
    """True se o nome do produto parece ser uma placa de vídeo RTX 5080 avulsa."""
    norm = _normalize(name)
    if not re.search(r"rtx[\s\-]*5080", norm):
        return False
    return not any(term in norm for term in _EXCLUDE_TERMS)


def parse_brl(text: str) -> Optional[float]:
    """Converte 'R$ 12.345,67' (ou variações) para 12345.67."""
    if not text:
        return None
    m = re.search(r"(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:,\d{2})?)", text.replace("\xa0", " "))
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


class BaseScraper(ABC):
    """Contrato de um scraper de loja."""

    store: str = ""
    store_label: str = ""
    timeout: float = 30.0

    @property
    def proxy(self) -> Optional[str]:
        """Proxy das coletas desta loja (SCRAPER_PROXY), se ela estiver no escopo.

        SCRAPER_PROXY_STORES limita quais lojas usam o proxy (padrão:
        "pichau,amazon" — as que sofrem anti-bot em IP de datacenter).
        Use "all" para rotear todas. Proxies residenciais costumam cobrar
        por GB; rotear a Terabyte (~650 KB/página) queimaria a franquia.
        """
        proxy = os.environ.get("SCRAPER_PROXY") or None
        if not proxy:
            return None
        stores = {
            s.strip().lower()
            for s in os.environ.get("SCRAPER_PROXY_STORES", "pichau,amazon,mercadolivre").split(",")
            if s.strip()
        }
        if stores & {"all", "*"} or self.store in stores:
            return proxy
        return None

    def make_client(self, **kwargs) -> httpx.AsyncClient:
        headers = {**BROWSER_HEADERS, **kwargs.pop("headers", {})}
        if self.proxy and "proxy" not in kwargs:
            kwargs["proxy"] = self.proxy
        return httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout,
            follow_redirects=True,
            **kwargs,
        )

    async def impersonated_request(self, method: str, url: str, *,
                                   headers: Optional[dict] = None,
                                   json_body: Any = None) -> Any:
        """Requisição com impressão digital TLS de navegador (curl_cffi).

        Cloudflare e afins identificam o TLS do Python mesmo com cabeçalhos
        de navegador; o curl_cffi imita o handshake do Chrome. Retorna None
        se a biblioteca não estiver instalada (o chamador usa httpx).
        """
        try:
            from curl_cffi import requests as cffi
        except ImportError:
            return None
        merged = {**BROWSER_HEADERS, **(headers or {})}

        kwargs: dict = {}
        if self.proxy:
            kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}

        def _do():
            return cffi.request(
                method, url, headers=merged, json=json_body,
                impersonate="chrome", timeout=self.timeout, allow_redirects=True,
                **kwargs,
            )

        return await asyncio.to_thread(_do)

    @abstractmethod
    async def fetch(self) -> list[Offer]:
        """Busca as ofertas atuais de RTX 5080 na loja. Levanta exceção em caso de falha."""

    def offer(self, name: str, price: float, url: str,
              price_card: Optional[float] = None, available: bool = True) -> Offer:
        return Offer(
            store=self.store,
            store_label=self.store_label,
            name=" ".join(name.split()),
            price=round(price, 2),
            price_card=round(price_card, 2) if price_card else None,
            url=url,
            available=available,
        )
