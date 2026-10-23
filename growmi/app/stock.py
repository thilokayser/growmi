from .plants import now_ts
from .i18n import tr


def set_stock(conn, fertilizer_id: int, ml: float, ts: str | None = None) -> None:
    conn.execute("UPDATE fertilizer SET bestand_ml=?, bestand_ab=? WHERE id=?", (ml, ts or now_ts(), fertilizer_id))
    conn.commit()


def status(conn, fertilizer_id: int) -> dict | None:
    """Remaining ml since the last stock count and how many waterings that still covers. None without a count."""
    f = conn.execute("SELECT * FROM fertilizer WHERE id=?", (fertilizer_id,)).fetchone()
    if f is None or f["bestand_ml"] is None:
        return None
    used = conn.execute(
        "SELECT COALESCE(SUM(wi.ml_total), 0) FROM watering_item wi JOIN watering w ON w.id=wi.watering_id"
        " WHERE wi.produkt=? AND wi.hersteller=? AND w.ts >= ?", (f["produkt"], f["hersteller"], f["bestand_ab"])).fetchone()[0]
    recent = [r[0] for r in conn.execute(
        "SELECT wi.ml_total FROM watering_item wi JOIN watering w ON w.id=wi.watering_id"
        " WHERE wi.produkt=? AND wi.hersteller=? ORDER BY w.ts DESC, w.id DESC LIMIT 5", (f["produkt"], f["hersteller"]))]
    rest = max(f["bestand_ml"] - used, 0.0)
    gaenge = rest / (sum(recent) / len(recent)) if recent and sum(recent) > 0 else None
    return {"id": f["id"], "produkt": f["produkt"], "hersteller": f["hersteller"], "rest_ml": rest, "gaenge": gaenge,
            "low": rest <= 0 or (gaenge is not None and gaenge < 2), "preis": f["preis_eur"], "flasche_ml": f["flasche_ml"]}


def add_bottle(conn, fertilizer_id: int, ts: str | None = None) -> None:
    f = conn.execute("SELECT flasche_ml FROM fertilizer WHERE id=?", (fertilizer_id,)).fetchone()
    if not f or not f["flasche_ml"]:
        raise ValueError(tr("Für eine neue Flasche bitte zuerst die Flaschengröße beim Dünger eintragen"))
    s = status(conn, fertilizer_id)
    set_stock(conn, fertilizer_id, (s["rest_ml"] if s else 0.0) + f["flasche_ml"], ts)


def all_status(conn) -> list[dict]:
    return [s for r in conn.execute("SELECT id FROM fertilizer ORDER BY produkt")
            if (s := status(conn, r["id"])) is not None]


def low_items(conn) -> list[dict]:
    return [s for s in all_status(conn) if s["low"]]
