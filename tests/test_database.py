from app.database import Database
from app.models import Offer


def make_offer(price: float, url: str = "https://loja/x", available: bool = True) -> Offer:
    return Offer(
        store="kabum", store_label="KaBuM!",
        name="Placa de Vídeo RTX 5080", price=price, url=url, available=available,
    )


def test_history_records_only_changes(tmp_path):
    db = Database(tmp_path / "t.db")
    db.replace_store_offers("kabum", [make_offer(9000.0)])
    db.replace_store_offers("kabum", [make_offer(9000.0)])  # sem mudança
    db.replace_store_offers("kabum", [make_offer(8800.0)])  # queda de preço

    hist = db.history(days=7)
    assert [h["price"] for h in hist] == [9000.0, 8800.0]

    offers = db.latest_offers()
    assert len(offers) == 1
    assert offers[0]["price"] == 8800.0
    db.close()


def test_latest_offers_sorted_available_first(tmp_path):
    db = Database(tmp_path / "t.db")
    db.replace_store_offers("kabum", [
        make_offer(9000.0, url="https://loja/a"),
        make_offer(7000.0, url="https://loja/b", available=False),
        make_offer(8500.0, url="https://loja/c"),
    ])
    offers = db.latest_offers()
    assert [o["price"] for o in offers] == [8500.0, 9000.0, 7000.0]
    db.close()


def test_best_history_anchors_stable_prices(tmp_path):
    # preço que não mudou dentro da janela ainda precisa aparecer no gráfico:
    # a âncora usa o último preço conhecido antes do início da janela
    db = Database(tmp_path / "t.db")
    old_ts = "2020-01-01T00:00:00+00:00"
    db._conn.execute(
        "INSERT INTO price_history (store, url, name, price, available, ts) "
        "VALUES ('kabum', 'https://loja/a', 'RTX 5080', 9000.0, 1, ?)",
        (old_ts,),
    )
    db._conn.commit()
    rows = db.best_history(days=1)
    assert len(rows) == 1
    assert rows[0]["price"] == 9000.0
    assert rows[0]["store"] == "kabum"
    db.close()


def test_delisted_product_recorded_as_unavailable(tmp_path):
    db = Database(tmp_path / "t.db")
    db.replace_store_offers("kabum", [make_offer(9000.0, url="https://loja/a")])
    db.replace_store_offers("kabum", [])  # produto sumiu da loja
    hist = db.history(days=7)
    assert [(h["price"], h["available"]) for h in hist] == [(9000.0, True), (9000.0, False)]
    db.close()


def test_best_history_anchor_skips_delisted(tmp_path):
    # último evento antes da janela é um delist: a âncora não pode
    # ressuscitar o produto no gráfico
    db = Database(tmp_path / "t.db")
    db._conn.executemany(
        "INSERT INTO price_history (store, url, name, price, available, ts) "
        "VALUES ('kabum', 'https://loja/a', 'RTX 5080', 9000.0, ?, ?)",
        [(1, "2020-01-01T00:00:00+00:00"), (0, "2020-01-02T00:00:00+00:00")],
    )
    db._conn.commit()
    assert db.best_history(days=1) == []
    db.close()


def test_best_history_min_per_hour(tmp_path):
    db = Database(tmp_path / "t.db")
    db.replace_store_offers("kabum", [
        make_offer(9000.0, url="https://loja/a"),
        make_offer(8500.0, url="https://loja/b"),
        make_offer(7000.0, url="https://loja/c", available=False),  # fora: indisponível
    ])
    rows = db.best_history(days=1)
    assert len(rows) == 1
    assert rows[0]["price"] == 8500.0
    assert rows[0]["store"] == "kabum"
    db.close()
