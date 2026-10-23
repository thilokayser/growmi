import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from . import calc, snapshot
from .settings import strompreis
from .web import get_conn

router = APIRouter()
CSV_COLUMNS = ["platz", "sorte", "hersteller", "keimdatum", "eingesetzt_am", "ausgezogen_am", "trocken_g", "nass_g",
               "wasser_l", "duenger_ml", "kwh", "kosten_eur", "g_pro_l", "g_pro_ml", "g_pro_kwh", "eur_pro_g",
               "bew_geschmack", "bew_wirkung", "bew_aufwand", "trocknung_tage"]


def _download(body: str, name: str, media: str) -> Response:
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/export.json")
def export_json(conn=Depends(get_conn)):
    return _download(snapshot.dump_json(conn), f"growmi-{date.today():%Y%m%d}.json", "application/json")


@router.get("/export.csv")
def export_csv(request: Request, conn=Depends(get_conn)):
    price = strompreis(request.app.state.ha, request.app.state.options)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLUMNS)
    for p in conn.execute("SELECT * FROM plant ORDER BY sorte, keimdatum, id"):
        t = calc.plant_totals(conn, p["id"], price)
        w.writerow([p["slot"], p["sorte"], p["hersteller"], p["keimdatum"], p["eingesetzt_am"], p["ausgezogen_am"],
                    p["trocken_g"], p["nass_g"], round(t.water_l, 2), round(sum(t.fert_ml.values()), 1), t.kwh,
                    t.cost_eur, t.g_per_l, t.g_per_ml, t.g_per_kwh, t.eur_per_g, p["bew_geschmack"],
                    p["bew_wirkung"], p["bew_aufwand"], p["trocknung_tage"]])
    return _download(out.getvalue(), f"growmi-auswertung-{date.today():%Y%m%d}.csv", "text/csv; charset=utf-8")
