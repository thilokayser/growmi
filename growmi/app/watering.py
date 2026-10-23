from typing import NamedTuple

from . import plants
from .i18n import tr


class RecipeItem(NamedTuple):
    fertilizer_id: int
    produkt: str
    hersteller: str
    ml_per_l: float


FERT_EDITABLE = {"produkt", "hersteller", "n", "p", "k", "filename", "preis_eur", "flasche_ml"}


def _check_npk(**parts) -> None:
    for name, v in parts.items():
        if v is not None and not 0 <= v <= 100:
            raise ValueError(tr("{name} muss zwischen 0 und 100 liegen", name=name.upper()))


def _check_price(**parts) -> None:
    for name, v in parts.items():
        if v is not None and v <= 0:
            raise ValueError(tr("{name} muss größer als 0 sein", name=name))


def add_fertilizer(conn, produkt: str, hersteller: str, *, n: float | None = None, p: float | None = None,
                   k: float | None = None, filename: str | None = None, preis_eur: float | None = None,
                   flasche_ml: float | None = None) -> int:
    _check_npk(n=n, p=p, k=k)
    _check_price(preis_eur=preis_eur, flasche_ml=flasche_ml)
    cur = conn.execute("INSERT INTO fertilizer(produkt, hersteller, n, p, k, filename, preis_eur, flasche_ml)"
                       " VALUES (?,?,?,?,?,?,?,?)", (produkt, hersteller, n, p, k, filename, preis_eur, flasche_ml))
    conn.commit()
    return cur.lastrowid


def update_fertilizer(conn, fertilizer_id: int, **fields) -> None:
    bad = set(fields) - FERT_EDITABLE
    if bad:
        raise ValueError(tr("Nicht änderbar: {bad}", bad=sorted(bad)))
    _check_npk(**{k: v for k, v in fields.items() if k in ("n", "p", "k")})
    _check_price(**{k: v for k, v in fields.items() if k in ("preis_eur", "flasche_ml")})
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE fertilizer SET {sets} WHERE id=?", (*fields.values(), fertilizer_id))
        conn.commit()


def delete_fertilizer(conn, fertilizer_id: int) -> str | None:
    """Returns the reference image filename (if any) so the caller can delete the file."""
    # watering_item holds a snapshot and has no link to fertilizer, so old entries stay intact
    row = conn.execute("SELECT filename FROM fertilizer WHERE id=?", (fertilizer_id,)).fetchone()
    conn.execute("DELETE FROM recipe_item WHERE fertilizer_id=?", (fertilizer_id,))
    conn.execute("DELETE FROM fertilizer WHERE id=?", (fertilizer_id,))
    conn.commit()
    return row["filename"] if row else None


def set_recipe(conn, box_phase: str, items: list[tuple[int, float]]) -> None:
    if box_phase not in plants.BOX_PHASES:
        raise ValueError(tr("Unbekannte Box-Phase: {phase!r}", phase=box_phase))
    known = {r[0] for r in conn.execute("SELECT id FROM fertilizer")}
    if any(fid not in known for fid, _ in items):
        raise ValueError(tr("Dünger existiert nicht mehr, bitte Seite neu laden"))
    conn.execute("DELETE FROM recipe_item WHERE box_phase=?", (box_phase,))
    conn.executemany("INSERT INTO recipe_item(box_phase, fertilizer_id, ml_per_l) VALUES (?,?,?)",
                     [(box_phase, fid, ml) for fid, ml in items])
    conn.commit()


def get_recipe(conn, box_phase: str) -> list[RecipeItem]:
    rows = conn.execute(
        "SELECT f.id, f.produkt, f.hersteller, r.ml_per_l FROM recipe_item r"
        " JOIN fertilizer f ON f.id=r.fertilizer_id WHERE r.box_phase=? ORDER BY f.produkt", (box_phase,))
    return [RecipeItem(*tuple(r)) for r in rows]


def add_watering(conn, *, ts: str, liters: float, items: list[tuple[int, float]],
                 plant_ids: list[int] | None = None, ph: float | None = None,
                 ec: float | None = None) -> int:
    if liters <= 0:
        raise ValueError(tr("Liter müssen größer als 0 sein"))
    if plant_ids is None:
        plant_ids = plants.occupied_plants(conn, ts)
    if not plant_ids:
        raise ValueError(tr("Keine Pflanze ausgewählt"))
    plant_ids = sorted(set(plant_ids))
    plants.require_plants(conn, plant_ids)
    cur = conn.execute("INSERT INTO watering(ts, liters, ph, ec) VALUES (?,?,?,?)", (ts, liters, ph, ec))
    wid = cur.lastrowid
    conn.executemany("INSERT INTO watering_plant(watering_id, plant_id) VALUES (?,?)",
                     [(wid, pid) for pid in plant_ids])
    for fid, ml_per_l in items:
        f = conn.execute("SELECT produkt, hersteller, preis_eur, flasche_ml FROM fertilizer WHERE id=?", (fid,)).fetchone()
        eur_per_ml = f["preis_eur"] / f["flasche_ml"] if f["preis_eur"] and f["flasche_ml"] else None
        conn.execute("INSERT INTO watering_item(watering_id, produkt, hersteller, ml_per_l, ml_total, eur_per_ml)"
                     " VALUES (?,?,?,?,?,?)", (wid, f["produkt"], f["hersteller"], ml_per_l, ml_per_l * liters, eur_per_ml))
    conn.commit()
    return wid


def set_week_plan(conn, box_phase: str, week: int, items: list[tuple[int, float]], water_only: bool) -> None:
    if box_phase not in plants.BOX_PHASES:
        raise ValueError(tr("Unbekannte Box-Phase: {phase!r}", phase=box_phase))
    known = {r[0] for r in conn.execute("SELECT id FROM fertilizer")}
    if any(fid not in known for fid, _ in items):
        raise ValueError(tr("Dünger existiert nicht mehr, bitte Seite neu laden"))
    conn.execute("DELETE FROM recipe_week WHERE box_phase=? AND week=?", (box_phase, week))
    conn.execute("DELETE FROM recipe_week_flag WHERE box_phase=? AND week=?", (box_phase, week))
    if items or water_only:
        conn.execute("INSERT INTO recipe_week_flag(box_phase, week, water_only) VALUES (?,?,?)", (box_phase, week, int(water_only)))
        conn.executemany("INSERT INTO recipe_week(box_phase, week, fertilizer_id, ml_per_l) VALUES (?,?,?,?)",
                         [(box_phase, week, fid, ml) for fid, ml in items])
    conn.commit()


def get_week_plan(conn, box_phase: str, week: int):
    flag = conn.execute("SELECT water_only FROM recipe_week_flag WHERE box_phase=? AND week=?", (box_phase, week)).fetchone()
    if flag is None:
        return None
    rows = conn.execute("SELECT f.id, f.produkt, f.hersteller, r.ml_per_l FROM recipe_week r JOIN fertilizer f"
                        " ON f.id=r.fertilizer_id WHERE r.box_phase=? AND r.week=? ORDER BY f.produkt", (box_phase, week))
    return [RecipeItem(*tuple(r)) for r in rows], bool(flag["water_only"])


def current_recipe(conn, today) -> dict:
    """What the box should get now: this week's plan if there is one, else the recipe of the box phase."""
    from . import jobs  # late import: jobs does not import this module, but keep the dependency one-way
    pw = jobs.phase_week(conn, today)
    if pw is None:
        return {"source": None, "items": [], "label": "", "phase": None, "week": None}
    phase, week = pw
    plan = get_week_plan(conn, phase, week)
    if plan:
        items, water_only = plan
        names = ", ".join(f"{i.produkt} {i.ml_per_l:g} ml/L" for i in items)
        label = tr("Wochenplan {phase} Woche {week}: ", phase=tr(phase), week=week) + (tr("Nur Wasser") if water_only else names)
        return {"source": "plan", "items": [(i.fertilizer_id, i.ml_per_l) for i in items], "label": label,
                "phase": phase, "week": week}
    items = get_recipe(conn, phase)
    return {"source": "phase", "items": [(i.fertilizer_id, i.ml_per_l) for i in items], "label": phase,
            "phase": phase, "week": week}


def items_for(conn, rezept: str, today) -> list[tuple[int, float]]:
    """Fertilizer items for the recipe choice of a watering form: a phase name, 'plan' or 'wasser'."""
    if rezept == "plan":
        cur = current_recipe(conn, today)
        if cur["source"] != "plan":
            raise ValueError(tr("Kein Wochenplan für diese Woche hinterlegt"))
        return cur["items"]
    if rezept in plants.BOX_PHASES:
        return [(r.fertilizer_id, r.ml_per_l) for r in get_recipe(conn, rezept)]
    return []
