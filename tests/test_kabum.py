import json

import pytest

from app.scrapers.kabum import KabumScraper

API_SAMPLE = {
    "data": [
        {
            "id": "123456",
            "type": "product",
            "attributes": {
                "title": "Placa de Vídeo RTX 5080 ASUS Prime OC 16GB GDDR7",
                "price": 10999.99,
                "price_with_discount": 9899.99,
                "available": True,
            },
        },
        {
            "id": "222222",
            "type": "product",
            "attributes": {
                "title": "Water Block para RTX 5080",
                "price": 999.99,
                "price_with_discount": 899.99,
                "available": True,
            },
        },
        {
            "id": "333333",
            "type": "product",
            "attributes": {
                "title": "Placa de Vídeo RTX 5080 Zotac 16GB",
                "price": 9500.0,
                "price_with_discount": 0,
                "available": False,
            },
        },
    ]
}


def test_parse_api_filters_and_prices():
    offers = KabumScraper().parse_api(API_SAMPLE)
    assert len(offers) == 2
    first = offers[0]
    assert first.price == 9899.99
    assert first.price_card == 10999.99
    assert first.url == "https://www.kabum.com.br/produto/123456"
    assert first.available is True
    # sem preço pix, usa preço cheio; disponibilidade preservada
    second = offers[1]
    assert second.price == 9500.0
    assert second.available is False


def test_parse_search_html_next_data():
    payload = {
        "props": {
            "pageProps": {
                "data": {
                    "catalogServer": {
                        "data": [
                            {
                                "name": "Placa de Vídeo RTX 5080 Galax 16GB",
                                "code": 987654,
                                "price": 10500.0,
                                "priceWithDiscount": 9450.0,
                                "available": True,
                            }
                        ]
                    }
                }
            }
        }
    }
    html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></html>'
    offers = KabumScraper().parse_search_html(html)
    assert len(offers) == 1
    assert offers[0].price == 9450.0
    assert offers[0].url == "https://www.kabum.com.br/produto/987654"


def test_parse_search_html_without_next_data_raises():
    with pytest.raises(RuntimeError):
        KabumScraper().parse_search_html("<html><body>bloqueado</body></html>")
