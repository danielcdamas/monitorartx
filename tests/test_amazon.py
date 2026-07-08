import pytest

from app.scrapers.amazon import AmazonScraper

SEARCH_HTML = """
<html><body>
<div data-component-type="s-search-result" data-asin="B0AAAA1111">
  <h2><span>MSI GeForce RTX 5080 Ventus 3X OC 16GB GDDR7</span></h2>
  <span class="a-price"><span class="a-offscreen">R$ 9.699,00</span></span>
  <span class="a-price a-text-price"><span class="a-offscreen">R$ 11.499,00</span></span>
</div>
<div data-component-type="s-search-result" data-asin="B0BBBB2222">
  <span class="puis-sponsored-label-text">Patrocinado</span>
  <h2><span>PNY GeForce RTX 5080 16GB</span></h2>
  <span class="a-price"><span class="a-offscreen">R$ 9.999,00</span></span>
</div>
<div data-component-type="s-search-result" data-asin="B0CCCC3333">
  <h2><span>Cabo adaptador 12VHPWR para RTX 5080</span></h2>
  <span class="a-price"><span class="a-offscreen">R$ 99,00</span></span>
</div>
</body></html>
"""


def test_parse_html_skips_sponsored_and_accessories():
    offers = AmazonScraper().parse_html(SEARCH_HTML)
    assert len(offers) == 1
    o = offers[0]
    assert o.price == 9699.00  # usa o preço real, não o "de" riscado
    assert o.url == "https://www.amazon.com.br/dp/B0AAAA1111"


def test_parse_html_detects_captcha():
    with pytest.raises(RuntimeError, match="captcha"):
        AmazonScraper().parse_html(
            "<html>Digite os caracteres que você vê — api-services-support@amazon.com</html>"
        )
