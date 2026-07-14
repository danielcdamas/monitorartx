"""API FastAPI + frontend estático do monitor de preços RTX 5080."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .database import Database
from .monitor import Monitor
from .scrapers import ALL_SCRAPERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DB_PATH = os.environ.get("DB_PATH", "prices.db")
STATIC_DIR = Path(__file__).parent / "static"

db = Database(DB_PATH)
monitor = Monitor(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    monitor.start()
    yield
    await monitor.stop()
    db.close()


app = FastAPI(title="Monitor RTX 5080", lifespan=lifespan)


@app.get("/api/offers")
async def get_offers():
    return monitor.snapshot()


@app.get("/api/best")
async def get_best():
    snap = monitor.snapshot()
    return {"best": snap["best"], "models": snap["models"], "generated_at": snap["generated_at"]}


@app.get("/api/history")
async def get_history(days: int = 7, model: str | None = None):
    days = max(1, min(days, 90))
    return {"days": days, "model": model, "series": db.best_history(days, model)}


@app.get("/api/status")
async def get_status():
    return {
        "last_cycle": monitor.last_cycle,
        "interval_seconds": monitor.snapshot()["interval_seconds"],
        "stores": [s.to_dict() for s in monitor.status.values()],
    }


@app.post("/api/refresh")
async def refresh_now():
    monitor.request_refresh()
    return {"ok": True, "message": "Atualização solicitada"}


@app.get("/api/diag/{store}")
async def diag(store: str):
    """Diagnóstico ao vivo de uma loja: mostra o que ela devolve ao servidor.

    Vale para qualquer loja registrada — inclusive as inativas no painel —
    para permitir depurar bloqueios sem precisar reativá-las.
    """
    scraper = next((cls() for cls in ALL_SCRAPERS if cls.store == store), None)
    if scraper is None:
        return {"error": f"loja desconhecida: {store}",
                "opções": [cls.store for cls in ALL_SCRAPERS]}
    if hasattr(scraper, "diagnose"):
        return await scraper.diagnose()
    try:
        offers = await scraper.fetch()
        return {"store": store, "ok": True, "offers": [o.to_dict() for o in offers]}
    except Exception as exc:
        return {"store": store, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


@app.get("/api/stream")
async def stream():
    """Server-Sent Events: empurra o snapshot completo a cada ciclo de coleta."""

    async def gen():
        import json
        # assina dentro do generator: se o cliente derrubar a conexão antes do
        # primeiro byte, nenhuma fila órfã fica registrada no monitor
        q = monitor.subscribe()
        try:
            # estado atual imediatamente ao conectar
            yield f"data: {json.dumps(monitor.snapshot(), ensure_ascii=False)}\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            monitor.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
