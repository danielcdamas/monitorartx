from datetime import datetime, timedelta, timezone

import app.monitor as monitor_mod
from app.database import Database
from app.models import Offer


def test_snapshot_excludes_stale_offers_from_best(tmp_path):
    db = Database(tmp_path / "t.db")
    interval = monitor_mod.SCRAPE_INTERVAL
    fresh_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stale_ts = (
        datetime.now(timezone.utc) - timedelta(seconds=4 * interval)
    ).isoformat(timespec="seconds")

    db.replace_store_offers("kabum", [Offer(
        store="kabum", store_label="KaBuM!", name="RTX 5080 A",
        price=9000.0, url="https://loja/fresca", scraped_at=fresh_ts,
    )])
    # loja que parou de responder: oferta mais barata, porém velha
    db.replace_store_offers("pichau", [Offer(
        store="pichau", store_label="Pichau", name="RTX 5080 B",
        price=7000.0, url="https://loja/velha", scraped_at=stale_ts,
    )])

    snap = monitor_mod.Monitor(db).snapshot()
    assert snap["best"]["url"] == "https://loja/fresca"
    stale_flags = {o["url"]: o["stale"] for o in snap["offers"]}
    assert stale_flags == {"https://loja/fresca": False, "https://loja/velha": True}
    db.close()
