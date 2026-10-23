from fastapi import APIRouter, Depends, Request

from . import calc, climate
from .settings import strompreis
from .web import get_conn, render

router = APIRouter()
RATINGS = (("bew_geschmack", "Geschmack"), ("bew_wirkung", "Wirkung"), ("bew_aufwand", "Aufwand"))


@router.get("/auswertung")
def auswertung(request: Request, conn=Depends(get_conn)):
    price = strompreis(request.app.state.ha, request.app.state.options)
    groups = calc.by_sorte(conn, price)
    every = [t for g in groups for t in g.plants]

    def top(attr):
        return max([getattr(t, attr) or 0 for t in every] or [0]) or 1

    # bars are relative to the largest value on the page so strains compare at a glance
    maxima = {"trocken_g": top("trocken_g"), "water_l": top("water_l"), "g_per_l": top("g_per_l")}
    info = {t.plant_id: conn.execute("SELECT * FROM plant WHERE id=?", (t.plant_id,)).fetchone() for t in every}
    avgs = {}
    for g in groups:
        parts = []
        for col, label in RATINGS:
            vals = [info[t.plant_id][col] for t in g.plants if info[t.plant_id][col] is not None]
            parts.append((label, sum(vals) / len(vals) if vals else None))
        avgs[g.sorte] = parts if any(v is not None for _, v in parts) else None
    return render(request, "auswertung.html", groups=groups, maxima=maxima, info=info, avgs=avgs,
                  klima=climate.phase_stats(conn), price=price, ranking=calc.ranking(conn, price))
