from app.scrapers import select_scrapers


def _ids(monkeypatch=None):
    return {s.store for s in select_scrapers()}


def test_default_hides_proxy_and_spa_stores(monkeypatch):
    monkeypatch.delenv("MONITOR_STORES", raising=False)
    monkeypatch.delenv("SCRAPER_PROXY", raising=False)
    ids = _ids()
    # sem proxy: só as lojas que coletam de graça na nuvem
    assert ids == {"terabyte", "kabum", "amazon"}
    assert "pichau" not in ids and "mercadolivre" not in ids  # requires_proxy
    assert "pcgamer" not in ids  # default_enabled False (SPA)


def test_proxy_reveals_proxy_stores(monkeypatch):
    monkeypatch.delenv("MONITOR_STORES", raising=False)
    monkeypatch.setenv("SCRAPER_PROXY", "http://user:pass@proxy:8080")
    ids = _ids()
    assert {"terabyte", "kabum", "amazon", "pichau", "mercadolivre"} <= ids
    assert "pcgamer" not in ids  # SPA continua fora sem pedido explícito


def test_monitor_stores_env_is_explicit_allowlist(monkeypatch):
    monkeypatch.delenv("SCRAPER_PROXY", raising=False)
    monkeypatch.setenv("MONITOR_STORES", "terabyte, pcgamer")
    ids = _ids()
    # allowlist explícita inclui até a loja SPA e ignora as demais
    assert ids == {"terabyte", "pcgamer"}
