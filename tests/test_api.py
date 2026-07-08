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
        assert snap["best"]["price"] == min(o["price"] for o in offers if o["available"])

        hist = client.get("/api/history?days=7").json()
        assert hist["series"], "histórico vazio após o primeiro ciclo"

        status = client.get("/api/status").json()
        assert len(status["stores"]) == 4
        assert all(s["ok"] for s in status["stores"])

        assert client.post("/api/refresh").json()["ok"] is True
