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
