"""Testes do backend PostgreSQL (PgDatabase).

Rodam apenas quando TEST_DATABASE_URL aponta para um Postgres de teste:
    TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5433/monitorartx pytest
Espelham os invariantes já testados no SQLite: mudanças de preço, delist,
âncora do gráfico e filtro por modelo.
"""
import os

import pytest

PG_DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not PG_DSN, reason="TEST_DATABASE_URL não definido")

from app.models import Offer  # noqa: E402


def make_offer(price, url="https://loja/x", available=True, model="rtx5080"):
    return Offer(
        store="kabum", store_label="KaBuM!",
        name="Placa de Vídeo RTX 5080", price=price, url=url,
        available=available, model=model,
    )


@pytest.fixture
def db():
    from app.database import PgDatabase
    d = PgDatabase(PG_DSN)
    d._run(lambda conn: conn.execute(
        "TRUNCATE offers, price_history, scrape_runs RESTART IDENTITY"
    ))
    yield d
    d.close()


def test_history_records_only_changes(db):
    db.replace_store_offers("kabum", [make_offer(9000.0)])
    db.replace_store_offers("kabum", [make_offer(9000.0)])  # sem mudança
    db.replace_store_offers("kabum", [make_offer(8800.0)])  # queda

    hist = db.history(days=7)
    assert [h["price"] for h in hist] == [9000.0, 8800.0]
    offers = db.latest_offers()
    assert len(offers) == 1 and offers[0]["price"] == 8800.0
    assert offers[0]["available"] is True


def test_delist_and_anchor(db):
    db.replace_store_offers("kabum", [make_offer(9000.0)])
    db.replace_store_offers("kabum", [])  # sumiu da loja
    hist = db.history(days=7)
    assert [(h["price"], h["available"]) for h in hist] == [(9000.0, True), (9000.0, False)]


def test_best_history_anchor_and_model_filter(db):
    # evento antigo (antes da janela) vira âncora no início dela
    db._run(lambda conn: conn.execute(
        "INSERT INTO price_history (store, url, name, price, available, model, ts) "
        "VALUES ('kabum', 'https://loja/a', 'RTX 5080', 9000.0, 1, 'rtx5080', "
        "'2020-01-01T00:00:00+00:00')"
    ))
    rows = db.best_history(days=1, model="rtx5080")
    assert len(rows) == 1 and rows[0]["price"] == 9000.0
    # filtro por modelo: 5090 não tem histórico
    assert db.best_history(days=1, model="rtx5090") == []


def test_best_history_min_per_hour_and_models(db):
    db.replace_store_offers("kabum", [
        make_offer(9000.0, url="https://loja/a"),
        make_offer(8500.0, url="https://loja/b"),
        make_offer(18000.0, url="https://loja/c", model="rtx5090"),
        make_offer(7000.0, url="https://loja/d", available=False),  # indisponível: fora
    ])
    r80 = db.best_history(days=1, model="rtx5080")
    assert len(r80) == 1 and r80[0]["price"] == 8500.0
    r90 = db.best_history(days=1, model="rtx5090")
    assert len(r90) == 1 and r90[0]["price"] == 18000.0


def test_record_run(db):
    db.record_run("kabum", True, None, 5)
    db.record_run("kabum", False, "erro X", 0)
    rows = db._run(lambda conn: conn.execute(
        "SELECT ok, error, offer_count FROM scrape_runs ORDER BY id"
    ).fetchall())
    assert [(r["ok"], r["offer_count"]) for r in rows] == [(1, 5), (0, 0)]
