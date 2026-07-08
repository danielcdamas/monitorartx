"""Persistência em SQLite: ofertas atuais, histórico de preços e status das coletas."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Optional

from .models import Offer, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    store       TEXT NOT NULL,
    store_label TEXT NOT NULL,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    price       REAL NOT NULL,
    price_card  REAL,
    available   INTEGER NOT NULL DEFAULT 1,
    scraped_at  TEXT NOT NULL,
    PRIMARY KEY (store, url)
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    store       TEXT NOT NULL,
    url         TEXT NOT NULL,
    name        TEXT NOT NULL,
    price       REAL NOT NULL,
    available   INTEGER NOT NULL DEFAULT 1,
    ts          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_store_ts ON price_history (store, ts);
CREATE INDEX IF NOT EXISTS idx_history_url_ts ON price_history (url, ts);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    store       TEXT NOT NULL,
    ts          TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    error       TEXT,
    offer_count INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    """Acesso thread-safe ao SQLite (o scheduler e a API compartilham a conexão)."""

    def __init__(self, path: str | Path = "prices.db") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ writes

    def replace_store_offers(self, store: str, offers: Iterable[Offer]) -> None:
        """Substitui o snapshot de ofertas da loja e registra histórico quando o preço muda."""
        offers = list(offers)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM offers WHERE store = ?", (store,))
            for o in offers:
                cur.execute(
                    "INSERT OR REPLACE INTO offers "
                    "(store, store_label, name, url, price, price_card, available, scraped_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (o.store, o.store_label, o.name, o.url, o.price,
                     o.price_card, int(o.available), o.scraped_at),
                )
                last = cur.execute(
                    "SELECT price, available FROM price_history WHERE url = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (o.url,),
                ).fetchone()
                if last is None or last["price"] != o.price or bool(last["available"]) != o.available:
                    cur.execute(
                        "INSERT INTO price_history (store, url, name, price, available, ts) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (o.store, o.url, o.name, o.price, int(o.available), o.scraped_at),
                    )
            self._conn.commit()

    def record_run(self, store: str, ok: bool, error: Optional[str], offer_count: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO scrape_runs (store, ts, ok, error, offer_count) VALUES (?, ?, ?, ?, ?)",
                (store, utcnow_iso(), int(ok), error, offer_count),
            )
            # mantém a tabela de runs enxuta
            self._conn.execute(
                "DELETE FROM scrape_runs WHERE id NOT IN "
                "(SELECT id FROM scrape_runs ORDER BY id DESC LIMIT 2000)"
            )
            self._conn.commit()

    # ------------------------------------------------------------------- reads

    def latest_offers(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM offers ORDER BY available DESC, price ASC"
            ).fetchall()
        return [dict(r) | {"available": bool(r["available"])} for r in rows]

    def history(self, days: int = 7) -> list[dict]:
        """Histórico de preços (apenas ofertas disponíveis) dos últimos N dias."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT store, url, name, price, available, ts FROM price_history "
                "WHERE datetime(ts) >= datetime('now', ?) ORDER BY ts ASC",
                (f"-{int(days)} days",),
            ).fetchall()
        return [dict(r) | {"available": bool(r["available"])} for r in rows]

    def best_history(self, days: int = 7) -> list[dict]:
        """Menor preço disponível por loja em janelas de 1 hora — alimenta o gráfico."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT store, strftime('%Y-%m-%dT%H:00:00', ts) AS hour, MIN(price) AS price
                FROM price_history
                WHERE available = 1 AND datetime(ts) >= datetime('now', ?)
                GROUP BY store, hour
                ORDER BY hour ASC
                """,
                (f"-{int(days)} days",),
            ).fetchall()
        return [dict(r) for r in rows]
