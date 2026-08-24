"""Resiliência a banco fora do ar: o painel nunca morre por causa do banco."""
import asyncio
import os
from datetime import datetime, timezone

import pytest

import app.monitor as monitor_mod
from app.database import Database, create_database
from app.models import Offer


def _offer(price=9000.0, url="https://loja/a"):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return Offer(store="kabum", store_label="KaBuM!", name="RTX 5080 X",
                 price=price, url=url, model="rtx5080", scraped_at=now)


def test_create_database_falls_back_to_sqlite(tmp_path, monkeypatch):
    # porta fechada: conexão recusada na hora — o app NÃO pode morrer
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:y@127.0.0.1:1/nada")
    db = create_database(tmp_path / "fb.db")
    assert isinstance(db, Database)
    db.close()


def test_snapshot_serves_from_memory_when_db_dies(tmp_path):
    db = Database(tmp_path / "t.db")
    db.replace_store_offers("kabum", [_offer()])
    mon = monitor_mod.Monitor(db)  # seed lido do banco
    assert mon.snapshot()["best"]["rtx5080"]["price"] == 9000.0

    # banco "morre": snapshot continua funcionando (memória)
    def boom():
        raise RuntimeError("banco fora")
    db.latest_offers = boom
    assert mon.snapshot()["best"]["rtx5080"]["price"] == 9000.0
    db.close()


def test_cycle_survives_persistence_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_STORES", "1")
    monkeypatch.setenv("MONITOR_STORES", "kabum")
    import importlib
    importlib.reload(monitor_mod)
    try:
        db = Database(tmp_path / "t.db")

        def boom(*a, **k):
            raise RuntimeError("cota estourada")
        db.replace_store_offers = boom
        db.record_run = boom

        mon = monitor_mod.Monitor(db)
        asyncio.run(mon.run_cycle())  # não pode levantar exceção
        snap = mon.snapshot()
        assert snap["offers"], "painel deve mostrar ofertas mesmo sem persistir"
        assert all(s["ok"] for s in snap["status"])
        db.close()
    finally:
        monkeypatch.undo()
        importlib.reload(monitor_mod)


def test_history_cache_hits_db_once(tmp_path):
    db = Database(tmp_path / "t.db")
    db.replace_store_offers("kabum", [_offer()])
    mon = monitor_mod.Monitor(db)
    calls = {"n": 0}
    original = db.best_history

    def counting(days, model=None):
        calls["n"] += 1
        return original(days, model)
    db.best_history = counting

    a = mon.best_history(7, "rtx5080")
    b = mon.best_history(7, "rtx5080")
    assert a == b and calls["n"] == 1  # 2ª chamada veio do cache
    mon.best_history(30, "rtx5080")
    assert calls["n"] == 2  # chave diferente consulta o banco
    db.close()


PG_DSN = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not PG_DSN, reason="TEST_DATABASE_URL não definido")
def test_reconnects_to_pg_when_it_returns(tmp_path, monkeypatch):
    from app.database import PgDatabase
    monkeypatch.setenv("DATABASE_URL", PG_DSN)
    db = Database(tmp_path / "t.db")  # começou em fallback SQLite
    mon = monitor_mod.Monitor(db)
    mon._pg_retry_countdown = 1  # força a tentativa neste ciclo
    asyncio.run(mon._maybe_reconnect_pg())
    assert isinstance(mon.db, PgDatabase)
    mon.db.close()
