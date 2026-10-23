from datetime import date, datetime, timedelta

from . import tasks
from .i18n import tr


def weekly(conn, now: datetime, strompreis: float) -> dict:
    start = (now - timedelta(days=7)).date()
    ts0 = start.isoformat()
    liters = conn.execute("SELECT COALESCE(SUM(liters), 0) FROM watering WHERE substr(ts,1,10) >= ?", (ts0,)).fetchone()[0]
    fert = conn.execute("SELECT COALESCE(SUM(wi.ml_total * wi.eur_per_ml), 0) FROM watering_item wi JOIN watering w"
                        " ON w.id=wi.watering_id WHERE substr(w.ts,1,10) >= ? AND wi.eur_per_ml IS NOT NULL", (ts0,)).fetchone()[0]
    kwh = conn.execute("SELECT COALESCE(SUM(kwh), 0) FROM climate_day WHERE day >= ?", (ts0,)).fetchone()[0]
    ok = conn.execute("SELECT AVG(vpd_ok_pct) FROM climate_day WHERE day >= ? AND vpd_ok_pct IS NOT NULL", (ts0,)).fetchone()[0]
    hitze = conn.execute("SELECT COUNT(*) FROM box_event WHERE kind='hitze' AND substr(ts,1,10) >= ?", (ts0,)).fetchone()[0]
    photos = [dict(r) for r in conn.execute(
        "SELECT p.sorte, p.slot, ph.filename FROM photo ph JOIN plant p ON p.id=ph.plant_id WHERE substr(ph.ts,1,10) >= ?"
        " AND ph.id IN (SELECT MAX(id) FROM photo GROUP BY plant_id) ORDER BY p.slot", (ts0,))]
    strom = kwh * strompreis
    return {"start": start, "liters": liters, "fert_eur": fert, "strom_eur": strom, "cost": fert + strom, "kwh": kwh,
            "ok_pct": ok, "hitze": hitze, "tasks_open": len(tasks.due_tasks(conn, now.date())), "photos": photos}


def text(r: dict) -> str:
    lines = [tr("Wochenbericht ab {start:%d.%m.}", start=r["start"]),
             tr("Gegossen: {l:g} L", l=r["liters"]),
             tr("Kosten: {cost:.2f} € (Dünger {fert:.2f} €, Strom {strom:.2f} € bei {kwh:.1f} kWh)", cost=r["cost"], fert=r["fert_eur"], strom=r["strom_eur"], kwh=r["kwh"]),
             tr("VPD im Ziel: {pct:.0f} %", pct=r["ok_pct"]) if r["ok_pct"] is not None else tr("VPD im Ziel: noch keine Daten"),
             tr("Hitze-Ereignisse: {n}", n=r["hitze"]), tr("Offene Aufgaben: {n}", n=r["tasks_open"])]
    return "\n".join(lines)
