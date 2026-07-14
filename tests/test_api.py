import importlib
import time


def test_api_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_STORES", "1")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("SCRAPE_INTERVAL_SECONDS", "3600")

    import app.monitor as monitor_mod
    importlib.reload(monitor_mod)  # relê MOCK_STORES/intervalo do ambiente
    import app.main as main
    importlib.reload(main)

    from fastapi.testclient import TestClient

    try:
        _run_smoke(main, TestClient)
    finally:
        # restaura os módulos para os demais testes (sem env de mock)
        monkeypatch.undo()
        importlib.reload(monitor_mod)
        importlib.reload(main)


def _run_smoke(main, TestClient):
    with TestClient(main.app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "Monitor RTX 5080" in r.text

        # espera o primeiro ciclo (lojas simuladas) popular o banco
        offers = []
        for _ in range(50):
            snap = client.get("/api/offers").json()
            offers = snap["offers"]
            if offers:
                break
            time.sleep(0.1)
        assert offers, "primeiro ciclo de coleta não produziu ofertas"

        # best é um dicionário por modelo; cada um é o menor preço do seu modelo
        assert set(snap["best"]) == {"rtx5080", "rtx5090"}
        for model in ("rtx5080", "rtx5090"):
            model_prices = [o["price"] for o in offers if o["available"] and o["model"] == model]
            assert snap["best"][model]["price"] == min(model_prices)
            assert snap["best"][model]["model"] == model

        hist = client.get("/api/history?days=7&model=rtx5090").json()
        assert hist["model"] == "rtx5090"
        assert hist["series"], "histórico do 5090 vazio após o primeiro ciclo"

        status = client.get("/api/status").json()
        assert len(status["stores"]) == 6
        assert all(s["ok"] for s in status["stores"])

        assert client.post("/api/refresh").json()["ok"] is True
