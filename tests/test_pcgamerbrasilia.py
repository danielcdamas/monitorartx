from app.scrapers.pcgamerbrasilia import PcGamerBrasiliaScraper

JSONLD_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "itemListElement": [
    {
      "@type": "Product",
      "name": "Placa de Vídeo RTX 5080 XFX Swift 16GB GDDR7",
      "url": "https://www.pcgamerbrasilia.com.br/placa-rtx-5080-xfx",
      "offers": {"@type": "Offer", "price": "9349.90", "availability": "https://schema.org/InStock"}
    },
    {
      "@type": "Product",
      "name": "Water Block para RTX 5080",
      "url": "/water-block",
      "offers": {"@type": "Offer", "price": "899.90", "availability": "InStock"}
    },
    {
      "@type": "Product",
      "name": "Placa de Vídeo RTX 5080 Galax 16GB",
      "url": "/placa-rtx-5080-galax",
      "offers": {"@type": "Offer", "price": "9899.90", "availability": "https://schema.org/OutOfStock"}
    }
  ]
}
</script>
</head><body></body></html>
"""

GENERIC_HTML = """
<html><body>
<div class="produto">
  <a href="/placa-rtx-5080-pcyes" title="Placa de Vídeo RTX 5080 PCYes 16GB GDDR7">RTX 5080 PCYes</a>
  <span class="preco">R$ 9.199,00</span>
</div>
<div class="produto">
  <a href="/mousepad" title="Mousepad Gamer RTX">Mousepad</a>
  <span class="preco">R$ 79,90</span>
</div>
</body></html>
"""


def test_parse_jsonld_filters_and_availability():
    offers = PcGamerBrasiliaScraper().parse_html(JSONLD_HTML)
    assert len(offers) == 2  # water block excluído pelo filtro de nome
    xfx = next(o for o in offers if "XFX" in o.name)
    assert xfx.price == 9349.90
    assert xfx.available is True
    assert xfx.url == "https://www.pcgamerbrasilia.com.br/placa-rtx-5080-xfx"
    galax = next(o for o in offers if "Galax" in o.name)
    assert galax.available is False
    assert galax.url == "https://www.pcgamerbrasilia.com.br/placa-rtx-5080-galax"


def test_parse_generic_fallback():
    offers = PcGamerBrasiliaScraper().parse_html(GENERIC_HTML)
    assert len(offers) == 1  # mousepad descartado (nome + piso de preço)
    assert offers[0].price == 9199.00
    assert offers[0].name.startswith("Placa de Vídeo RTX 5080 PCYes")
