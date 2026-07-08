"""Diagnóstico: roda cada scraper uma vez e imprime o resultado.

Uso:
    python -m app.check              # todas as lojas
    python -m app.check kabum pichau # lojas específicas
"""
from __future__ import annotations

import asyncio
import sys

from .scrapers import ALL_SCRAPERS


async def main(stores: list[str]) -> int:
    scrapers = [cls() for cls in ALL_SCRAPERS]
    if stores:
        scrapers = [s for s in scrapers if s.store in stores]
        if not scrapers:
            print(f"lojas desconhecidas: {stores} — opções: "
                  f"{[cls().store for cls in ALL_SCRAPERS]}")
            return 2

    failures = 0
    for s in scrapers:
        print(f"\n=== {s.store_label} ({s.store}) " + "=" * 40)
        try:
            offers = await s.fetch()
        except Exception as exc:
            failures += 1
            print(f"  ERRO: {type(exc).__name__}: {exc}")
            continue
        if not offers:
            print("  (nenhuma oferta encontrada)")
            continue
        for o in sorted(offers, key=lambda o: o.price):
            stock = "em estoque" if o.available else "ESGOTADO  "
            print(f"  R$ {o.price:>9,.2f}  [{stock}]  {o.name[:70]}")
            print(f"               {o.url}")
    print(f"\n{len(scrapers) - failures}/{len(scrapers)} lojas responderam com sucesso.")
    return 0 if failures < len(scrapers) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
