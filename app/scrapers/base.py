"""Infraestrutura comum dos scrapers: HTTP, parse de preço BRL e filtro de produto."""
from __future__ import annotations

import asyncio
import os
import re
import unicodedata
from abc import ABC
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

# Modelos monitorados. A ordem define a ordem no painel. Para acrescentar um
# modelo (ex.: RTX 5070 Ti), basta adicionar uma entrada aqui — scrapers,
# banco e frontend são model-agnostic e se adaptam.
MODELS: dict[str, dict] = {
    "rtx5080": {"label": "RTX 5080", "num": "5080", "search": "rtx 5080"},
    "rtx5090": {"label": "RTX 5090", "num": "5090", "search": "rtx 5090"},
}
DEFAULT_MODEL = next(iter(MODELS))
# termos de busca usados pelos scrapers (um por modelo)
SEARCH_QUERIES = [m["search"] for m in MODELS.values()]

# Termos que indicam que o item NÃO é uma placa de vídeo avulsa.
_EXCLUDE_TERMS = [
    "water block", "waterblock", "bloco de agua", "block acetal",
    "suporte", "bracket", "cabo", "adaptador", "backplate",
    "pc gamer", "computador", "desktop", "notebook", "laptop",
    "workstation", "monitor", "gabinete", "fonte", "kit upgrade",
    "mochila", "camiseta", "mousepad",
]

_MODEL_RE = {mid: re.compile(rf"rtx[\s\-]*{m['num']}") for mid, m in MODELS.items()}


def _normalize(text: str) -> str:
    # ™/® antes do NFKD: senão "RTX™" vira "rtxtm" e o regex não casa
    text = text.replace("™", " ").replace("®", " ")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def classify_model(name: str) -> Optional[str]:
    """Retorna o id do modelo monitorado (ex.: 'rtx5080') ou None.

    None quando o nome não é uma placa avulsa de um modelo monitorado
    (acessório, PC montado, ou outro modelo como 5070).
    """
    if not name:
        return None
    norm = _normalize(name)
    if any(term in norm for term in _EXCLUDE_TERMS):
        return None
    for mid, rx in _MODEL_RE.items():
        if rx.search(norm):
            return mid
    return None


def is_target_gpu(name: str) -> bool:
    """True se o nome é uma placa avulsa de algum modelo monitorado."""
    return classify_model(name) is not None


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
    # loja que só coleta em hospedagem na nuvem através de proxy residencial
    # (muro de login/anti-bot contra IP de datacenter) — some do painel se
    # não houver SCRAPER_PROXY configurado
    requires_proxy: bool = False
    # loja incluída no monitoramento por padrão (False = só via MONITOR_STORES)
    default_enabled: bool = True

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

    async def fetch(self) -> list[Offer]:
        """Coleta as ofertas de todos os modelos monitorados.

        Faz uma busca por termo de modelo (RTX 5080, RTX 5090, …) e junta
        os resultados; cada oferta é classificada pelo nome real, então uma
        busca que traga o modelo "errado" ainda rotula corretamente.
        Só levanta erro se TODAS as buscas falharem sem produzir nada.
        """
        merged: dict[str, Offer] = {}
        errors: list[Exception] = []
        for query in SEARCH_QUERIES:
            try:
                for o in await self._search(query):
                    merged[o.url] = o
            except Exception as exc:
                errors.append(exc)
        if not merged and errors:
            raise errors[0]
        return list(merged.values())

    async def _search(self, query: str) -> list[Offer]:
        """Busca uma loja por um termo (ex.: "rtx 5090") e devolve as ofertas.

        Deve devolver [] quando não há resultados (não é erro) e levantar
        exceção só em falha real (bloqueio, HTTP erro, estrutura ausente).
        """
        raise NotImplementedError

    def offer(self, name: str, price: float, url: str,
              price_card: Optional[float] = None, available: bool = True,
              model: Optional[str] = None) -> Offer:
        return Offer(
            store=self.store,
            store_label=self.store_label,
            name=" ".join(name.split()),
            price=round(price, 2),
            price_card=round(price_card, 2) if price_card else None,
            url=url,
            available=available,
            model=model or classify_model(name) or DEFAULT_MODEL,
        )
