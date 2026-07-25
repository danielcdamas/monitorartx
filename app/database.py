"""Persistência: ofertas atuais, histórico de preços e status das coletas.

Dois backends com o mesmo contrato:
- Database (SQLite): padrão para rodar localmente.
- PgDatabase (PostgreSQL): ativado por DATABASE_URL — essencial em hospedagens
  de disco efêmero (Render free apaga o sistema de arquivos a cada hibernação/
  deploy, zerando o SQLite); um Postgres gerenciado gratuito (ex.: Neon)
  preserva o histórico de 7/30 dias entre restarts.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Optional

from .models import Offer, utcnow_iso

log = logging.getLogger("database")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    store       TEXT NOT NULL,
    store_label TEXT NOT NULL,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    price       REAL NOT NULL,
    price_card  REAL,
    available   INTEGER NOT NULL DEFAULT 1,
    model       TEXT NOT NULL DEFAULT 'rtx5080',
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
    model       TEXT NOT NULL DEFAULT 'rtx5080',
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
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """Adiciona colunas novas a bancos antigos (ex.: 'model')."""
        for table in ("offers", "price_history"):
            cols = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if "model" not in cols:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN model TEXT NOT NULL DEFAULT 'rtx5080'"
                )
        # índice em model só depois de garantir a coluna (bancos antigos)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_history_model_ts ON price_history (model, ts)"
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ writes

    def replace_store_offers(self, store: str, offers: Iterable[Offer]) -> None:
        """Substitui o snapshot de ofertas da loja e registra histórico quando o preço muda."""
        offers = list(offers)
        now = utcnow_iso()
        with self._lock:
            cur = self._conn.cursor()
            # produto que sumiu da loja: registra o delist para o histórico
            # não continuar reportando o último preço como disponível
            new_urls = {o.url for o in offers}
            for row in cur.execute(
                "SELECT url, name, price, model FROM offers WHERE store = ?", (store,)
            ).fetchall():
                if row["url"] in new_urls:
                    continue
                last = cur.execute(
                    "SELECT available FROM price_history WHERE url = ? ORDER BY id DESC LIMIT 1",
                    (row["url"],),
                ).fetchone()
                if last is not None and bool(last["available"]):
                    cur.execute(
                        "INSERT INTO price_history (store, url, name, price, available, model, ts) "
                        "VALUES (?, ?, ?, ?, 0, ?, ?)",
                        (store, row["url"], row["name"], row["price"], row["model"], now),
                    )
            cur.execute("DELETE FROM offers WHERE store = ?", (store,))
            for o in offers:
                cur.execute(
                    "INSERT OR REPLACE INTO offers "
                    "(store, store_label, name, url, price, price_card, available, model, scraped_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (o.store, o.store_label, o.name, o.url, o.price,
                     o.price_card, int(o.available), o.model, o.scraped_at),
                )
                last = cur.execute(
                    "SELECT price, available FROM price_history WHERE url = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (o.url,),
                ).fetchone()
                if last is None or last["price"] != o.price or bool(last["available"]) != o.available:
                    cur.execute(
                        "INSERT INTO price_history (store, url, name, price, available, model, ts) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (o.store, o.url, o.name, o.price, int(o.available), o.model, o.scraped_at),
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

    def best_history(self, days: int = 7, model: Optional[str] = None) -> list[dict]:
        """Menor preço disponível por loja/hora, de um modelo — alimenta o gráfico.

        Como o histórico só grava MUDANÇAS de preço, cada loja ganha uma
        "âncora" no início da janela com seu último preço conhecido antes
        dela — sem isso, uma loja de preço estável sumiria do gráfico.
        """
        off = f"-{int(days)} days"
        params: dict = {"off": off}
        anchor_filter = window_filter = ""
        if model:
            anchor_filter = "AND p.model = :model"
            window_filter = "AND model = :model"
            params["model"] = model
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT store, hour, MIN(price) AS price FROM (
                    SELECT p.store AS store,
                           strftime('%Y-%m-%dT%H:00:00', datetime('now', :off)) AS hour,
                           p.price AS price
                    FROM price_history p
                    WHERE p.available = 1 {anchor_filter}
                      AND p.id = (SELECT MAX(q.id) FROM price_history q
                                  WHERE q.url = p.url
                                    AND datetime(q.ts) < datetime('now', :off))
                    UNION ALL
                    SELECT store, strftime('%Y-%m-%dT%H:00:00', ts) AS hour, price
                    FROM price_history
                    WHERE available = 1 {window_filter} AND datetime(ts) >= datetime('now', :off)
                )
                GROUP BY store, hour
                ORDER BY hour ASC
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]


_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    store       TEXT NOT NULL,
    store_label TEXT NOT NULL,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    price_card  DOUBLE PRECISION,
    available   INTEGER NOT NULL DEFAULT 1,
    model       TEXT NOT NULL DEFAULT 'rtx5080',
    scraped_at  TEXT NOT NULL,
    PRIMARY KEY (store, url)
);

CREATE TABLE IF NOT EXISTS price_history (
    id          BIGSERIAL PRIMARY KEY,
    store       TEXT NOT NULL,
    url         TEXT NOT NULL,
    name        TEXT NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    available   INTEGER NOT NULL DEFAULT 1,
    model       TEXT NOT NULL DEFAULT 'rtx5080',
    ts          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_store_ts ON price_history (store, ts);
CREATE INDEX IF NOT EXISTS idx_history_url_ts ON price_history (url, ts);
CREATE INDEX IF NOT EXISTS idx_history_model_ts ON price_history (model, ts);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id          BIGSERIAL PRIMARY KEY,
    store       TEXT NOT NULL,
    ts          TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    error       TEXT,
    offer_count INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE offers        ADD COLUMN IF NOT EXISTS model TEXT NOT NULL DEFAULT 'rtx5080';
ALTER TABLE price_history ADD COLUMN IF NOT EXISTS model TEXT NOT NULL DEFAULT 'rtx5080';
"""


class PgDatabase:
    """Mesmo contrato de Database, em PostgreSQL (para hospedagem sem disco).

    Uma conexão compartilhada protegida por lock, com UMA reconexão
    automática por operação: provedores gratuitos (Neon) suspendem conexões
    ociosas, e o primeiro acesso após a pausa falharia sem o retry.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg
        from psycopg.rows import dict_row

        self._psycopg = psycopg
        self._dict_row = dict_row
        self._dsn = dsn
        self._conn = None
        self._lock = threading.Lock()
        self._run(lambda conn: conn.execute(_PG_SCHEMA))

    # ------------------------------------------------------------ infra

    def _ensure_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._psycopg.connect(self._dsn, row_factory=self._dict_row)
        return self._conn

    def _run(self, fn):
        """Executa fn(conn) e comita, reconectando uma vez se a conexão caiu."""
        with self._lock:
            for attempt in (1, 2):
                conn = self._ensure_conn()
                try:
                    result = fn(conn)
                    conn.commit()
                    return result
                except self._psycopg.OperationalError:
                    # conexão suspensa/derrubada pelo provedor: reconecta e repete
                    try:
                        conn.close()
                    except Exception:
                        pass
                    self._conn = None
                    if attempt == 2:
                        raise
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise

    def close(self) -> None:
        with self._lock:
            if self._conn is not None and not self._conn.closed:
                self._conn.close()

    # ----------------------------------------------------------- writes

    def replace_store_offers(self, store: str, offers: Iterable[Offer]) -> None:
        offers = list(offers)
        now = utcnow_iso()

        def op(conn):
            cur = conn.cursor()
            new_urls = {o.url for o in offers}
            cur.execute("SELECT url, name, price, model FROM offers WHERE store = %s", (store,))
            for row in cur.fetchall():
                if row["url"] in new_urls:
                    continue
                cur.execute(
                    "SELECT available FROM price_history WHERE url = %s ORDER BY id DESC LIMIT 1",
                    (row["url"],),
                )
                last = cur.fetchone()
                if last is not None and bool(last["available"]):
                    cur.execute(
                        "INSERT INTO price_history (store, url, name, price, available, model, ts) "
                        "VALUES (%s, %s, %s, %s, 0, %s, %s)",
                        (store, row["url"], row["name"], row["price"], row["model"], now),
                    )
            cur.execute("DELETE FROM offers WHERE store = %s", (store,))
            for o in offers:
                cur.execute(
                    "INSERT INTO offers "
                    "(store, store_label, name, url, price, price_card, available, model, scraped_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (store, url) DO UPDATE SET "
                    "store_label = EXCLUDED.store_label, name = EXCLUDED.name, "
                    "price = EXCLUDED.price, price_card = EXCLUDED.price_card, "
                    "available = EXCLUDED.available, model = EXCLUDED.model, "
                    "scraped_at = EXCLUDED.scraped_at",
                    (o.store, o.store_label, o.name, o.url, o.price,
                     o.price_card, int(o.available), o.model, o.scraped_at),
                )
                cur.execute(
                    "SELECT price, available FROM price_history WHERE url = %s "
                    "ORDER BY id DESC LIMIT 1",
                    (o.url,),
                )
                last = cur.fetchone()
                if last is None or last["price"] != o.price or bool(last["available"]) != o.available:
                    cur.execute(
                        "INSERT INTO price_history (store, url, name, price, available, model, ts) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (o.store, o.url, o.name, o.price, int(o.available), o.model, o.scraped_at),
                    )

        self._run(op)

    def record_run(self, store: str, ok: bool, error: Optional[str], offer_count: int) -> None:
        def op(conn):
            conn.execute(
                "INSERT INTO scrape_runs (store, ts, ok, error, offer_count) "
                "VALUES (%s, %s, %s, %s, %s)",
                (store, utcnow_iso(), int(ok), error, offer_count),
            )
            conn.execute(
                "DELETE FROM scrape_runs WHERE id NOT IN "
                "(SELECT id FROM scrape_runs ORDER BY id DESC LIMIT 2000)"
            )

        self._run(op)

    # ------------------------------------------------------------ reads

    def latest_offers(self) -> list[dict]:
        def op(conn):
            cur = conn.execute("SELECT * FROM offers ORDER BY available DESC, price ASC")
            return cur.fetchall()

        rows = self._run(op)
        return [dict(r) | {"available": bool(r["available"])} for r in rows]

    def history(self, days: int = 7) -> list[dict]:
        def op(conn):
            cur = conn.execute(
                "SELECT store, url, name, price, available, model, ts FROM price_history "
                "WHERE ts::timestamptz >= now() - make_interval(days => %s) ORDER BY ts ASC",
                (int(days),),
            )
            return cur.fetchall()

        rows = self._run(op)
        return [dict(r) | {"available": bool(r["available"])} for r in rows]

    def best_history(self, days: int = 7, model: Optional[str] = None) -> list[dict]:
        params: dict = {"days": int(days)}
        anchor_filter = window_filter = ""
        if model:
            anchor_filter = "AND p.model = %(model)s"
            window_filter = "AND model = %(model)s"
            params["model"] = model
        sql = f"""
            SELECT store, hour, MIN(price) AS price FROM (
                SELECT p.store AS store,
                       to_char(date_trunc('hour',
                           (now() - make_interval(days => %(days)s)) AT TIME ZONE 'UTC'),
                           'YYYY-MM-DD"T"HH24:00:00') AS hour,
                       p.price AS price
                FROM price_history p
                WHERE p.available = 1 {anchor_filter}
                  AND p.id = (SELECT MAX(q.id) FROM price_history q
                              WHERE q.url = p.url
                                AND q.ts::timestamptz < now() - make_interval(days => %(days)s))
                UNION ALL
                SELECT store,
                       to_char(ts::timestamptz AT TIME ZONE 'UTC',
                           'YYYY-MM-DD"T"HH24:00:00') AS hour,
                       price
                FROM price_history
                WHERE available = 1 {window_filter}
                  AND ts::timestamptz >= now() - make_interval(days => %(days)s)
            ) AS t
            GROUP BY store, hour
            ORDER BY hour ASC
        """

        def op(conn):
            return conn.execute(sql, params).fetchall()

        return [dict(r) for r in self._run(op)]


def create_database(path: str | Path = "prices.db"):
    """Postgres se DATABASE_URL estiver definido; senão SQLite local."""
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        log.info("usando PostgreSQL (DATABASE_URL) — histórico persistente")
        return PgDatabase(dsn)
    log.info("usando SQLite em %s", path)
    return Database(path)
