from app.scrapers.mercadolivre import MercadoLivreScraper
from app.scrapers.pichau import PichauScraper
from app.scrapers.terabyte import TerabyteScraper


def test_proxy_default_scope(monkeypatch):
    monkeypatch.setenv("SCRAPER_PROXY", "http://user:pass@proxy:8080")
    monkeypatch.delenv("SCRAPER_PROXY_STORES", raising=False)
    # padrão: só as lojas com anti-bot/login-wall de datacenter usam o proxy
    assert PichauScraper().proxy == "http://user:pass@proxy:8080"
    assert MercadoLivreScraper().proxy == "http://user:pass@proxy:8080"
    assert TerabyteScraper().proxy is None


def test_proxy_all_stores(monkeypatch):
    monkeypatch.setenv("SCRAPER_PROXY", "http://proxy:8080")
    monkeypatch.setenv("SCRAPER_PROXY_STORES", "all")
    assert TerabyteScraper().proxy == "http://proxy:8080"


def test_proxy_disabled_without_env(monkeypatch):
    monkeypatch.delenv("SCRAPER_PROXY", raising=False)
    assert PichauScraper().proxy is None
