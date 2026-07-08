from app.scrapers.terabyte import TerabyteScraper

CARD_HTML = """
<html><body>
<div class="pbox">
  <a href="/produto/12345/placa-de-video-asus-rtx-5080" title="Placa de Vídeo ASUS TUF RTX 5080 OC 16GB GDDR7">
    <h2>Placa de Vídeo ASUS TUF RTX 5080 OC 16GB GDDR7</h2>
  </a>
  <div class="prod-old-price">R$ 11.999,00</div>
  <div class="prod-new-price"><span>R$ 9.899,90</span></div>
  <div>à vista no PIX ou em até 12x de R$ 999,99</div>
</div>
<div class="pbox">
  <a href="/produto/67890/water-block-rtx-5080" title="Water Block Bykski RTX 5080">
    <h2>Water Block Bykski RTX 5080</h2>
  </a>
  <div class="prod-new-price"><span>R$ 1.299,90</span></div>
</div>
<div class="pbox">
  <a href="/produto/55555/placa-gigabyte-rtx-5080" title="Placa de Vídeo Gigabyte RTX 5080 Windforce 16GB">
    <h2>Placa de Vídeo Gigabyte RTX 5080 Windforce 16GB</h2>
  </a>
  <div class="prod-new-price"><span>R$ 9.299,90</span></div>
  <button>Avise-me</button> <span>Indisponível</span>
</div>
</body></html>
"""


def test_parse_html_extracts_prices_and_stock():
    offers = TerabyteScraper().parse_html(CARD_HTML)
    assert len(offers) == 2

    asus = next(o for o in offers if "ASUS" in o.name)
    assert asus.price == 9899.90
    assert asus.price_card == 11999.00  # preço mais alto do card, não a parcela
    assert asus.available is True
    assert asus.url == "https://www.terabyteshop.com.br/produto/12345/placa-de-video-asus-rtx-5080"

    giga = next(o for o in offers if "Gigabyte" in o.name)
    assert giga.available is False


def test_parse_html_ignores_installments():
    html = """
    <div><a href="/produto/1/rtx-5080" title="RTX 5080 Zotac 16GB">RTX 5080 Zotac 16GB</a>
    <p>12x de R$ 850,00 sem juros ou R$ 8.999,00 à vista</p></div>
    """
    offers = TerabyteScraper().parse_html(html)
    assert len(offers) == 1
    assert offers[0].price == 8999.00
