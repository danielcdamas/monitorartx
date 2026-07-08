import pytest

from app.scrapers.pichau import PichauScraper

GRAPHQL_SAMPLE = {
    "data": {
        "products": {
            "total_count": 2,
            "items": [
                {
                    "sku": "GB-RTX5080",
                    "name": "Placa de Video Gigabyte GeForce RTX 5080 Gaming OC 16GB",
                    "url_key": "placa-de-video-gigabyte-rtx-5080-gaming-oc",
                    "stock_status": "IN_STOCK",
                    "special_price": 9049.90,
                    "price_range": {
                        "minimum_price": {
                            "regular_price": {"value": 10645.76},
                            "final_price": {"value": 9049.90},
                        }
                    },
                },
                {
                    "sku": "WB-RTX5080",
                    "name": "Water Block Alphacool para RTX 5080",
                    "url_key": "water-block-rtx-5080",
                    "stock_status": "IN_STOCK",
                    "special_price": None,
                    "price_range": {
                        "minimum_price": {
                            "regular_price": {"value": 1500.0},
                            "final_price": {"value": 1400.0},
                        }
                    },
                },
                {
                    "sku": "MSI-RTX5080",
                    "name": "Placa de Video MSI GeForce RTX 5080 Ventus 3X 16GB",
                    "url_key": "placa-de-video-msi-rtx-5080-ventus",
                    "stock_status": "OUT_OF_STOCK",
                    "special_price": None,
                    "price_range": {
                        "minimum_price": {
                            "regular_price": {"value": 9999.0},
                            "final_price": {"value": 9399.0},
                        }
                    },
                },
            ],
        }
    }
}


def test_parse_graphql():
    offers = PichauScraper().parse_graphql(GRAPHQL_SAMPLE)
    assert len(offers) == 2

    gb = offers[0]
    assert gb.price == 9049.90
    assert gb.price_card == 10645.76
    assert gb.url == "https://www.pichau.com.br/placa-de-video-gigabyte-rtx-5080-gaming-oc"
    assert gb.available is True

    msi = offers[1]
    assert msi.price == 9399.0
    assert msi.available is False


def test_parse_graphql_error_raises():
    with pytest.raises(RuntimeError):
        PichauScraper().parse_graphql({"errors": [{"message": "Internal server error"}]})
