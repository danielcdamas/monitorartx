"""Orquestra os ciclos de coleta e distribui atualizações em tempo real (SSE)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from .database import Database
from .models import StoreStatus, utcnow_iso
from .scrapers import select_scrapers
from .scrapers.base import DEFAULT_MODEL, MODELS

log = logging.getLogger("monitor")

SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL_SECONDS", "180"))
SCRAPER_TIMEOUT = int(os.environ.get("SCRAPER_TIMEOUT_SECONDS", "90"))
MOCK_STORES = os.environ.get("MOCK_STORES", "").lower() in ("1", "true", "yes")
# em fallback SQLite (Postgres fora do ar no boot), tenta reconectar ao
# Postgres a cada N ciclos (~1 h com o intervalo padrão de 3 min)
PG_RETRY_CYCLES = int(os.environ.get("PG_RETRY_CYCLES", "20"))


class Monitor:
    def __init__(self, db: Database) -> None:
        self.db = db
        if MOCK_STORES:
            from .scrapers.mock import build_mock_scrapers
            log.warning("MOCK_STORES ativo — usando lojas simuladas (modo demo)")
            scrapers = build_mock_scrapers()
            env = os.environ.get("MONITOR_STORES", "").strip()
            if env:
                wanted = {s.strip().lower() for s in env.split(",") if s.strip()}
                scrapers = [s for s in scrapers if s.store in wanted]
            self.scrapers = scrapers
        else:
            self.scrapers = select_scrapers()
        log.info("lojas monitoradas: %s", ", ".join(s.store for s in self.scrapers))
        self.status: dict[str, StoreStatus] = {
            s.store: StoreStatus(store=s.store, store_label=s.store_label)
            for s in self.scrapers
        }
        self._subscribers: set[asyncio.Queue] = set()
        self._task: Optional[asyncio.Task] = None
        self._refresh_event = asyncio.Event()
        self._cycle_lock = asyncio.Lock()
        self.last_cycle: Optional[str] = None

        # O painel é servido DESTA memória; o banco fica só para o histórico.
        # Assim, banco fora do ar = histórico pausado, nunca painel morto —
        # e o consumo de dados do Postgres gerenciado despenca.
        self._live_offers: dict[str, list[dict]] = {}
        self._history_cache: dict[tuple, list] = {}
        self._pg_retry_countdown = PG_RETRY_CYCLES
        try:
            for row in self.db.latest_offers():  # aquece com o último estado salvo
                if row["store"] in self.status:
                    self._live_offers.setdefault(row["store"], []).append(row)
        except Exception as exc:
            log.warning("sem seed do banco (%s) — painel começa vazio até o 1º ciclo",
                        f"{type(exc).__name__}: {exc}"[:150])

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
            # limpa ANTES do ciclo: um refresh pedido durante a coleta
            # sobrevive até o wait() e dispara novo ciclo imediatamente
            self._refresh_event.clear()
            try:
                await self.run_cycle()
            except Exception:  # nunca deixa o loop morrer
                log.exception("ciclo de coleta falhou")
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
            await self._maybe_reconnect_pg()
            await asyncio.gather(*(self._run_one(s) for s in self.scrapers))
            self.last_cycle = utcnow_iso()
            self._history_cache.clear()  # ciclo novo: histórico pode ter mudado
            self._broadcast(self.snapshot())

    async def _run_one(self, scraper) -> None:
        st = self.status[scraper.store]
        st.last_attempt = utcnow_iso()
        try:
            offers = await asyncio.wait_for(scraper.fetch(), timeout=SCRAPER_TIMEOUT)
        except Exception as exc:
            st.ok = False
            st.error = f"{type(exc).__name__}: {exc}"[:300]
            st.offer_count = 0
            try:
                await asyncio.to_thread(self.db.record_run, scraper.store, False, st.error, 0)
            except Exception:
                pass  # banco fora não pode piorar a situação
            log.warning("[%s] falha: %s", scraper.store, st.error)
            return
        st.ok = True
        st.error = None
        st.last_success = utcnow_iso()
        st.offer_count = len(offers)
        # o painel é atualizado ANTES (e independentemente) da persistência
        self._live_offers[scraper.store] = [o.to_dict() for o in offers]
        try:
            # sqlite comita com fsync — fora do event loop
            await asyncio.to_thread(self.db.replace_store_offers, scraper.store, offers)
            await asyncio.to_thread(self.db.record_run, scraper.store, True, None, len(offers))
        except Exception as exc:
            log.warning("[%s] persistência falhou (histórico pausado): %s",
                        scraper.store, f"{type(exc).__name__}: {exc}"[:150])
        log.info("[%s] %d ofertas", scraper.store, len(offers))

    async def _maybe_reconnect_pg(self) -> None:
        """Em fallback SQLite com DATABASE_URL definido, retenta o Postgres."""
        from .database import Database as _Sqlite, PgDatabase

        dsn = os.environ.get("DATABASE_URL")
        if not dsn or not isinstance(self.db, _Sqlite):
            return
        self._pg_retry_countdown -= 1
        if self._pg_retry_countdown > 0:
            return
        self._pg_retry_countdown = PG_RETRY_CYCLES
        try:
            newdb = await asyncio.to_thread(PgDatabase, dsn)
        except Exception as exc:
            log.info("Postgres ainda indisponível (%s) — seguindo no SQLite",
                     f"{type(exc).__name__}: {exc}"[:150])
            return
        old = self.db
        self.db = newdb
        log.warning("Postgres voltou — histórico persistente reativado")
        try:
            old.close()
        except Exception:
            pass

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

    def best_history(self, days: int, model: Optional[str] = None) -> list[dict]:
        """Histórico para o gráfico, com cache por ciclo (poupa o banco)."""
        key = (days, model)
        if key not in self._history_cache:
            try:
                self._history_cache[key] = self.db.best_history(days, model)
            except Exception as exc:
                log.warning("histórico indisponível no banco: %s",
                            f"{type(exc).__name__}: {exc}"[:150])
                return []
        return self._history_cache[key]

    def snapshot(self) -> dict:
        # cópias: o snapshot anota 'stale' sem tocar no estado vivo
        offers = [dict(o) for lst in self._live_offers.values() for o in lst]
        offers.sort(key=lambda o: (not o["available"], o["price"]))
        # oferta de loja que parou de responder não pode ficar valendo como
        # "melhor preço" para sempre: marca como desatualizada após 3 ciclos
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=3 * SCRAPE_INTERVAL)
        ).isoformat(timespec="seconds")
        for o in offers:
            o["stale"] = o["scraped_at"] < cutoff  # ISO UTC compara lexicograficamente
            o.setdefault("model", DEFAULT_MODEL)
        # melhor preço por modelo monitorado
        best: dict = {}
        for mid in MODELS:
            cand = [o for o in offers
                    if o.get("model") == mid and o["available"] and not o["stale"]]
            best[mid] = min(cand, key=lambda o: o["price"]) if cand else None
        return {
            "type": "update",
            "generated_at": utcnow_iso(),
            "last_cycle": self.last_cycle,
            "interval_seconds": SCRAPE_INTERVAL,
            "models": [{"id": mid, "label": m["label"]} for mid, m in MODELS.items()],
            "default_model": DEFAULT_MODEL,
            "best": best,
            "offers": offers,
            "status": [s.to_dict() for s in self.status.values()],
        }
