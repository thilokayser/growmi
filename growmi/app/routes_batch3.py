from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from . import config, entries, jobs, planner, plants, report, settings, stock, watering
from .routes_fertilizer import _fert_or_404
from .web import get_conn, redirect, render
from .i18n import tr

router = APIRouter()
WEEKS = range(1, 13)


@router.get("/einkauf")
def shopping(request: Request, conn=Depends(get_conn)):
    return render(request, "einkauf.html", items=stock.low_items(conn))


@router.post("/stammdaten/duenger/{fertilizer_id}/flasche")
def new_bottle(request: Request, fertilizer_id: int, conn=Depends(get_conn)):
    _fert_or_404(conn, fertilizer_id)
    try:
        stock.add_bottle(conn, fertilizer_id)
    except ValueError as e:
        return render(request, "einkauf.html", 400, items=stock.low_items(conn), error=str(e))
    return redirect(request, "/einkauf")


@router.get("/bericht")
def weekly_report(request: Request, conn=Depends(get_conn)):
    r = report.weekly(conn, datetime.now(), settings.strompreis(request.app.state.ha, request.app.state.options))
    return render(request, "bericht.html", r=r, text=report.text(r))


@router.get("/planung")
def planning(request: Request, conn=Depends(get_conn)):
    return render(request, "planung.html", rows=planner.forecast(conn, date.today()), germ=planner.GERM_DAYS)


@router.get("/probleme")
def problems(request: Request, tag: str = "", conn=Depends(get_conn)):
    where, args = ("AND i.tag = ?", (tag,)) if tag in entries.TAGS else ("", ())
    rows = conn.execute(f"SELECT i.*, p.sorte, p.slot FROM intervention i JOIN plant p ON p.id=i.plant_id"
                        f" WHERE i.tag IS NOT NULL {where} ORDER BY i.ts DESC", args).fetchall()
    items = []
    for r in rows:
        photos = [x["filename"] for x in conn.execute(
            "SELECT filename FROM photo WHERE plant_id=? AND ABS(julianday(substr(ts,1,10)) - julianday(?)) <= 1 ORDER BY ts",
            (r["plant_id"], r["ts"][:10]))]
        items.append({**dict(r), "photos": photos})
    counts = conn.execute("SELECT p.sorte, i.tag, COUNT(*) AS n FROM intervention i JOIN plant p ON p.id=i.plant_id"
                          " WHERE i.tag IS NOT NULL GROUP BY p.sorte, i.tag ORDER BY p.sorte, n DESC").fetchall()
    return render(request, "probleme.html", items=items, counts=counts, tags=entries.TAGS, tag=tag)


def _plan_ctx(conn, phase: str):
    fert = conn.execute("SELECT id, produkt FROM fertilizer ORDER BY produkt").fetchall()
    plan = {w: watering.get_week_plan(conn, phase, w) for w in WEEKS}
    return {"phase": phase, "phases": plants.BOX_PHASES, "fert": fert, "weeks": WEEKS, "plan": plan}


@router.get("/stammdaten/wochenplan")
def week_plan(request: Request, phase: str = "Blüte", conn=Depends(get_conn)):
    return render(request, "wochenplan.html", error=None, **_plan_ctx(conn, phase if phase in plants.BOX_PHASES else "Blüte"))


@router.post("/stammdaten/wochenplan/{phase}")
async def save_week_plan(request: Request, phase: str, conn=Depends(get_conn)):
    if phase not in plants.BOX_PHASES:
        return render(request, "wochenplan.html", 400, error=tr("Unbekannte Phase"), **_plan_ctx(conn, "Blüte"))
    form = await request.form()
    try:
        for w in WEEKS:
            items = [(int(k.split("_")[2]), plants.parse_decimal(v)) for k, v in form.items()
                     if k.startswith(f"ml_{w}_") and str(v).strip()]
            watering.set_week_plan(conn, phase, w, items, water_only=f"wasser_{w}" in form)
    except ValueError as e:
        return render(request, "wochenplan.html", 400, error=str(e), **_plan_ctx(conn, phase))
    return redirect(request, f"/stammdaten/wochenplan?phase={phase}")


@router.get("/verschleiss")
def wear_page(request: Request, conn=Depends(get_conn)):
    return render(request, "verschleiss.html", devices=jobs.device_status(conn, date.today()), error=None)


@router.post("/verschleiss/{key}/getauscht")
def wear_reset(request: Request, key: str, conn=Depends(get_conn)):
    if key not in jobs.device_keys():
        raise HTTPException(404)
    jobs.reset_wear(conn, key, date.today())
    return redirect(request, "/verschleiss")


@router.post("/verschleiss/{key}/limit")
def wear_limit(request: Request, key: str, limit_h: str = Form(""), conn=Depends(get_conn)):
    if key not in jobs.device_keys():
        raise HTTPException(404)
    try:
        jobs.set_wear_limit(conn, key, plants.parse_decimal(limit_h))
    except ValueError as e:
        return render(request, "verschleiss.html", 400, devices=jobs.device_status(conn, date.today()), error=str(e))
    return redirect(request, "/verschleiss")


@router.post("/cockpit/wartung")
def maintenance(request: Request, aktion: str = Form(""), conn=Depends(get_conn)):
    if aktion not in ("start", "ende"):
        raise HTTPException(400)
    timer = config.entity("maintenance")
    if not timer:
        raise HTTPException(400)
    request.app.state.ha.call_service("timer", "start" if aktion == "start" else "cancel", {"entity_id": timer})
    return redirect(request, "/cockpit")
