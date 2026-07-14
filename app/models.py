"""Modelos de dados do monitor de preços."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Offer:
    """Uma oferta de placa de vídeo encontrada em uma loja."""

    store: str            # id da loja: terabyte | kabum | pichau | amazon | ...
    store_label: str      # nome exibível: "Terabyteshop", "KaBuM!", ...
    name: str             # nome do produto
    price: float          # melhor preço à vista/pix em BRL
    url: str              # link do produto
    price_card: Optional[float] = None   # preço parcelado/cartão, se houver
    available: bool = True
    model: str = "rtx5080"   # modelo monitorado: rtx5080 | rtx5090 | ...
    scraped_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StoreStatus:
    """Estado da última coleta de uma loja."""

    store: str
    store_label: str
    ok: bool = False
    last_success: Optional[str] = None
    last_attempt: Optional[str] = None
    error: Optional[str] = None
    offer_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)
