"""Orquestra os ciclos de coleta e distribui atualizações em tempo real (SSE)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from .database import Database
from .models import StoreStatus, utcnow_iso
from .scrapers import ALL_SCRAPERS

log = logging.getLogger("monitor")

SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL_SECONDS", "180"))
SCRAPER_TIMEOUT = int(os.environ.get("SCRAPER_TIMEOUT_SECONDS", "90"))
MOCK_STORES = os.environ.get("MOCK_STORES", "").lower() in ("1", "true", "yes")


class Monitor:
    def __init__(self, db: Database) -> None:
        self.db = db
        if MOCK_STORES:
            from .scrapers.mock import build_mock_scrapers
            log.warning("MOCK_STORES ativo — usando lojas simuladas (modo demo)")
            self.scrapers = build_mock_scrapers()
        else:
            self.scrapers = [cls() for cls in ALL_SCRAPERS]
        self.status: dict[str, StoreStatus] = {
            s.store: StoreStatus(store=s.store, store_label=s.store_label)
            for s in self.scrapers
        }
        self._subscribers: set[asyncio.Queue] = set()
        self._task: Optional[asyncio.Task] = None
        self._refresh_event = asyncio.Event()
        self._cycle_lock = asyncio.Lock()
        self.last_cycle: Optional[str] = None

    # --------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_cycle()
            except Exception:  # nunca deixa o loop morrer
                log.exception("ciclo de coleta falhou")
            self._refresh_event.clear()
            try:
                # acorda antes se alguém pedir refresh manual
                await asyncio.wait_for(self._refresh_event.wait(), timeout=SCRAPE_INTERVAL)
            except asyncio.TimeoutError:
                pass

    def request_refresh(self) -> None:
        self._refresh_event.set()

    # ------------------------------------------------------------------ ciclo

    async def run_cycle(self) -> None:
        """Roda todos os scrapers em paralelo e publica o resultado."""
        async with self._cycle_lock:
            await asyncio.gather(*(self._run_one(s) for s in self.scrapers))
            self.last_cycle = utcnow_iso()
            self._broadcast(self.snapshot())

    async def _run_one(self, scraper) -> None:
        st = self.status[scraper.store]
        st.last_attempt = utcnow_iso()
        try:
            offers = await asyncio.wait_for(scraper.fetch(), timeout=SCRAPER_TIMEOUT)
        except Exception as exc:
            st.ok = False
            st.error = f"{type(exc).__name__}: {exc}"[:300]
            self.db.record_run(scraper.store, False, st.error, 0)
            log.warning("[%s] falha: %s", scraper.store, st.error)
            return
        st.ok = True
        st.error = None
        st.last_success = utcnow_iso()
        st.offer_count = len(offers)
        self.db.replace_store_offers(scraper.store, offers)
        self.db.record_run(scraper.store, True, None, len(offers))
        log.info("[%s] %d ofertas", scraper.store, len(offers))

    # -------------------------------------------------------------------- SSE

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=16)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _broadcast(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        for q in list(self._subscribers):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass  # assinante lento perde um frame; o próximo traz o estado completo

    # ----------------------------------------------------------------- estado

    def snapshot(self) -> dict:
        offers = self.db.latest_offers()
        available = [o for o in offers if o["available"]]
        best = min(available, key=lambda o: o["price"]) if available else None
        return {
            "type": "update",
            "generated_at": utcnow_iso(),
            "last_cycle": self.last_cycle,
            "interval_seconds": SCRAPE_INTERVAL,
            "best": best,
            "offers": offers,
            "status": [s.to_dict() for s in self.status.values()],
        }
