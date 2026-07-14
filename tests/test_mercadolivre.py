
from app.scrapers.mercadolivre import MercadoLivreScraper

SEARCH_HTML = """
<html><body>
<ol class="ui-search-layout">
  <li class="ui-search-layout__item">
    <div class="poly-card">
      <a class="poly-component__title" href="https://www.mercadolivre.com.br/rtx-5080-asus-tuf/p/MLB123">
        Placa de Vídeo ASUS TUF Gaming RTX 5080 OC 16GB GDDR7
      </a>
      <div class="poly-price__current">
        <span class="andes-money-amount andes-money-amount--previous">
          <span class="andes-money-amount__fraction">11.999</span>
        </span>
        <span class="andes-money-amount">
          <span class="andes-money-amount__fraction">9.899</span>
          <span class="andes-money-amount__cents">90</span>
        </span>
      </div>
    </div>
  </li>
  <li class="ui-search-layout__item">
    <div class="poly-card">
      <a class="poly-component__title" href="https://www.mercadolivre.com.br/rtx-5080-usada/p/MLB999">
        Placa de Vídeo RTX 5080 Gigabyte 16GB (USADO)
      </a>
      <div class="poly-price__current">
        <span class="andes-money-amount"><span class="andes-money-amount__fraction">7.500</span></span>
      </div>
    </div>
  </li>
  <li class="ui-search-layout__item">
    <div class="poly-card">
      <a class="poly-component__title" href="https://www.mercadolivre.com.br/cooler-rtx/p/MLB111">
        Cooler Cooler para Placa RTX 5080
      </a>
      <div class="poly-price__current">
        <span class="andes-money-amount"><span class="andes-money-amount__fraction">89</span></span>
      </div>
    </div>
  </li>
</ol>
</body></html>
"""


def test_parse_html_price_and_filters():
    offers = MercadoLivreScraper().parse_html(SEARCH_HTML)
    assert len(offers) == 1  # usado e cooler descartados
    o = offers[0]
    assert o.price == 9899.90  # usa o preço vigente, não o "de" riscado
    assert o.url == "https://www.mercadolivre.com.br/rtx-5080-asus-tuf/p/MLB123"
    assert o.store == "mercadolivre"


def test_parse_html_empty_returns_list():
    # busca sem resultados não é erro (o modelo pode não estar à venda)
    assert MercadoLivreScraper().parse_html("<html><body>sem resultados</body></html>") == []
