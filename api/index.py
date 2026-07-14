"""Entrada serverless (Vercel).

Sem processo em segundo plano nem SQLite: a coleta acontece sob demanda,
com cache em memória enquanto a função estiver quente. O frontend detecta
mode="serverless" e passa a fazer polling, guardando o histórico do gráfico
no localStorage do navegador.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))  # permite importar o pacote app/

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import utcnow_iso
from app.scrapers import select_scrapers
from app.scrapers.base import DEFAULT_MODEL, MODELS

CACHE_TTL = int(os.environ.get("CACHE_TTL_SECONDS", "120"))
STORE_TIMEOUT = int(os.environ.get("SCRAPER_TIMEOUT_SECONDS", "25"))
STATIC_DIR = ROOT / "app" / "static"

if os.environ.get("MOCK_STORES", "").lower() in ("1", "true", "yes"):
    from app.scrapers.mock import build_mock_scrapers
    _scrapers = build_mock_scrapers()
else:
    _scrapers = select_scrapers()

app = FastAPI(title="Monitor RTX 5080 (serverless)")

_cache: dict = {"ts": 0.0, "snapshot": None}
_lock = asyncio.Lock()


async def _scrape_all() -> dict:
    now = utcnow_iso()
    status: list[dict] = []
    offers: list[dict] = []

    async def one(scraper) -> None:
        st = {
            "store": scraper.store, "store_label": scraper.store_label,
            "ok": False, "last_success": None, "last_attempt": now,
            "error": None, "offer_count": 0,
        }
        try:
            found = await asyncio.wait_for(scraper.fetch(), timeout=STORE_TIMEOUT)
        except Exception as exc:
            st["error"] = f"{type(exc).__name__}: {exc}"[:300]
        else:
            st.update(ok=True, last_success=now, offer_count=len(found))
            offers.extend(o.to_dict() | {"stale": False} for o in found)
        status.append(st)

    await asyncio.gather(*(one(s) for s in _scrapers))
    offers.sort(key=lambda o: (not o["available"], o["price"]))
    best: dict = {}
    for mid in MODELS:
        cand = [o for o in offers if o.get("model") == mid and o["available"]]
        best[mid] = min(cand, key=lambda o: o["price"]) if cand else None
    return {
        "type": "update",
        "mode": "serverless",
        "generated_at": now,
        "last_cycle": now,
        "interval_seconds": CACHE_TTL,
        "models": [{"id": mid, "label": m["label"]} for mid, m in MODELS.items()],
        "default_model": DEFAULT_MODEL,
        "best": best,
        "offers": offers,
        "status": status,
    }


async def _get_snapshot(force: bool = False) -> dict:
    async with _lock:
        age = time.time() - _cache["ts"]
        if _cache["snapshot"] is None or age > CACHE_TTL or force:
            _cache["snapshot"] = await _scrape_all()
            _cache["ts"] = time.time()
        return _cache["snapshot"]


@app.get("/api/offers")
async def get_offers():
    return await _get_snapshot()


@app.get("/api/best")
async def get_best():
    snap = await _get_snapshot()
    return {"best": snap["best"], "models": snap["models"], "generated_at": snap["generated_at"]}


@app.get("/api/status")
async def get_status():
    snap = await _get_snapshot()
    return {
        "last_cycle": snap["last_cycle"],
        "interval_seconds": snap["interval_seconds"],
        "stores": snap["status"],
    }


@app.post("/api/refresh")
async def refresh_now():
    await _get_snapshot(force=True)
    return {"ok": True, "message": "Coleta atualizada"}


@app.get("/api/history")
async def get_history(days: int = 7):
    # sem banco no serverless: o histórico vive no localStorage do navegador
    return {"days": days, "series": [], "client_side": True}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
