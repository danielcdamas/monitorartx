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


WOOCOMMERCE_HTML = """
<html><head><title>PC Gamer Brasília</title></head><body>
<ul class="products columns-4">
  <li class="product type-product instock">
    <a href="https://www.pcgamerbrasilia.com.br/produto/rtx-5080-galax" class="woocommerce-LoopProduct-link">
      <h2 class="woocommerce-loop-product__title">Placa de Vídeo Galax GeForce RTX 5080 SG 16GB GDDR7</h2>
      <span class="price">
        <del><span class="woocommerce-Price-amount amount"><bdi>R$&nbsp;11.499,00</bdi></span></del>
        <ins><span class="woocommerce-Price-amount amount"><bdi>R$&nbsp;9.549,90</bdi></span></ins>
      </span>
    </a>
  </li>
  <li class="product type-product outofstock">
    <a href="https://www.pcgamerbrasilia.com.br/produto/rtx-5080-pny" class="woocommerce-LoopProduct-link">
      <h2 class="woocommerce-loop-product__title">Placa de Vídeo PNY GeForce RTX 5080 16GB</h2>
      <span class="price"><span class="woocommerce-Price-amount amount"><bdi>R$&nbsp;9.899,00</bdi></span></span>
    </a>
  </li>
  <li class="product type-product instock">
    <a href="https://www.pcgamerbrasilia.com.br/produto/cabo" class="woocommerce-LoopProduct-link">
      <h2 class="woocommerce-loop-product__title">Cabo Adaptador 12VHPWR para RTX 5080</h2>
      <span class="price"><span class="woocommerce-Price-amount amount"><bdi>R$&nbsp;149,00</bdi></span></span>
    </a>
  </li>
</ul>
</body></html>
"""


STORE_API_JSON = [
    {
        "id": 1,
        "name": "Placa de Vídeo XFX GeForce RTX 5080 Swift 16GB GDDR7",
        "permalink": "https://www.pcgamerbrasilia.com.br/produto/rtx-5080-xfx",
        "is_in_stock": True,
        "prices": {"price": "934990", "regular_price": "999990",
                   "sale_price": "934990", "currency_minor_unit": 2, "currency_code": "BRL"},
    },
    {
        "id": 2,
        "name": "Water Block EK para RTX 5080",
        "permalink": "https://www.pcgamerbrasilia.com.br/produto/water-block",
        "is_in_stock": True,
        "prices": {"price": "129990", "currency_minor_unit": 2},
    },
    {
        "id": 3,
        "name": "Placa de Vídeo Galax RTX 5080 16GB",
        "permalink": "https://www.pcgamerbrasilia.com.br/produto/rtx-5080-galax",
        "is_in_stock": False,
        "prices": {"price": "989900", "currency_minor_unit": 2},
    },
]


def test_parse_store_api():
    offers = PcGamerBrasiliaScraper()._parse_store_api(STORE_API_JSON)
    assert len(offers) == 2  # water block descartado
    xfx = next(o for o in offers if "XFX" in o.name)
    assert xfx.price == 9349.90  # 934990 / 100
    assert xfx.available is True
    assert xfx.url == "https://www.pcgamerbrasilia.com.br/produto/rtx-5080-xfx"
    galax = next(o for o in offers if "Galax" in o.name)
    assert galax.price == 9899.00
    assert galax.available is False


def test_parse_woocommerce_sale_price_stock_and_filter():
    offers = PcGamerBrasiliaScraper().parse_html(WOOCOMMERCE_HTML)
    assert len(offers) == 2  # cabo descartado pelo filtro de nome
    galax = next(o for o in offers if "Galax" in o.name)
    assert galax.price == 9549.90  # preço promocional (ins), não o riscado (del)
    assert galax.available is True
    assert galax.url == "https://www.pcgamerbrasilia.com.br/produto/rtx-5080-galax"
    pny = next(o for o in offers if "PNY" in o.name)
    assert pny.price == 9899.00
    assert pny.available is False  # classe outofstock


def test_parse_generic_fallback():
    offers = PcGamerBrasiliaScraper().parse_html(GENERIC_HTML)
    assert len(offers) == 1  # mousepad descartado (nome + piso de preço)
    assert offers[0].price == 9199.00
    assert offers[0].name.startswith("Placa de Vídeo RTX 5080 PCYes")
