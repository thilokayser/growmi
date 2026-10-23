from dataclasses import dataclass, field

from . import plants


@dataclass
class PlantTotals:
    plant_id: int
    sorte: str
    water_l: float = 0.0
    fert_ml: dict[str, float] = field(default_factory=dict)
    trocken_g: float | None = None
    g_per_l: float | None = None
    g_per_ml: float | None = None  # per ml of all fertilizer combined
    fert_eur: float | None = None
    kwh: float | None = None
    strom_eur: float | None = None
    cost_eur: float | None = None
    g_per_kwh: float | None = None
    eur_per_g: float | None = None


@dataclass
class SorteRow:
    sorte: str
    plants: list[PlantTotals]


def days_since_water(conn, plant_id: int, today) -> int | None:
    row = conn.execute("SELECT MAX(w.ts) FROM watering w JOIN watering_plant wp ON wp.watering_id=w.id"
                       " WHERE wp.plant_id=?", (plant_id,)).fetchone()[0]
    return (today - type(today).fromisoformat(row[:10])).days if row else None


def _kwh_share(conn, plant_id: int) -> float | None:
    """Box energy of each day, split between the plants that stood in the box that day."""
    total, seen = 0.0, False
    for r in conn.execute("SELECT day, kwh FROM climate_day WHERE kwh IS NOT NULL"):
        ids = plants.occupied_plants(conn, f"{r['day']}T12:00")
        if plant_id in ids:
            total, seen = total + r["kwh"] / len(ids), True
    return total if seen else None


def plant_totals(conn, plant_id: int, strompreis: float = 0.0) -> PlantTotals:
    p = conn.execute("SELECT sorte, trocken_g FROM plant WHERE id=?", (plant_id,)).fetchone()
    # each watering is shared equally between the plants it was recorded for
    waterings = conn.execute(
        "SELECT w.id, w.liters, (SELECT COUNT(*) FROM watering_plant WHERE watering_id=w.id) AS n"
        " FROM watering w JOIN watering_plant wp ON wp.watering_id=w.id WHERE wp.plant_id=?", (plant_id,)
    ).fetchall()
    water = sum(w["liters"] / w["n"] for w in waterings)
    fert: dict[str, float] = {}
    eur: float | None = None
    for w in waterings:
        for i in conn.execute("SELECT produkt, ml_total, eur_per_ml FROM watering_item WHERE watering_id=?", (w["id"],)):
            fert[i["produkt"]] = fert.get(i["produkt"], 0.0) + i["ml_total"] / w["n"]
            if i["eur_per_ml"] is not None:
                eur = (eur or 0.0) + i["ml_total"] / w["n"] * i["eur_per_ml"]
    trocken = p["trocken_g"]
    total_ml = sum(fert.values())
    kwh = _kwh_share(conn, plant_id)
    strom = kwh * strompreis if kwh is not None and strompreis > 0 else None
    costs = [c for c in (eur, strom) if c is not None]
    cost = sum(costs) if costs else None
    return PlantTotals(
        plant_id=plant_id, sorte=p["sorte"], water_l=water, fert_ml=fert, trocken_g=trocken,
        g_per_l=trocken / water if trocken and water > 0 else None,
        g_per_ml=trocken / total_ml if trocken and total_ml > 0 else None,
        fert_eur=eur, kwh=kwh, strom_eur=strom, cost_eur=cost,
        g_per_kwh=trocken / kwh if trocken and kwh else None,
        eur_per_g=cost / trocken if trocken and cost else None)


def by_sorte(conn, strompreis: float = 0.0) -> list[SorteRow]:
    rows = conn.execute("SELECT id, sorte FROM plant ORDER BY sorte, keimdatum, id").fetchall()
    groups: dict[str, list[PlantTotals]] = {}
    for r in rows:
        groups.setdefault(r["sorte"], []).append(plant_totals(conn, r["id"], strompreis))
    return [SorteRow(s, ps) for s, ps in groups.items()]


def ranking(conn, strompreis: float = 0.0) -> list[dict]:
    """One row per strain with at least one harvested plant, best average yield first."""
    out = []
    for g in by_sorte(conn, strompreis):
        done = [t for t in g.plants if t.trocken_g]
        if not done:
            continue
        marks = []
        for t in done:
            r = conn.execute("SELECT bew_geschmack, bew_wirkung, bew_aufwand FROM plant WHERE id=?", (t.plant_id,)).fetchone()
            marks += [v for v in tuple(r) if v is not None]
        per_eur = [1 / t.eur_per_g for t in done if t.eur_per_g]
        per_kwh = [t.g_per_kwh for t in done if t.g_per_kwh]
        out.append({"sorte": g.sorte, "n": len(done), "avg_g": sum(t.trocken_g for t in done) / len(done),
                    "avg_g_per_eur": sum(per_eur) / len(per_eur) if per_eur else None,
                    "avg_g_per_kwh": sum(per_kwh) / len(per_kwh) if per_kwh else None,
                    "avg_bew": sum(marks) / len(marks) if marks else None})
    return sorted(out, key=lambda r: -r["avg_g"])
