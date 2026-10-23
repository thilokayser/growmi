from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import cockpit, config, entries, jobs, plants, qr, tasks, watering
from .routes_home import live_values
from .routes_plants import _plant_or_404
from .web import get_conn, redirect, render

router = APIRouter()


@router.get("/platz/{slot}")
def slot_entry(request: Request, slot: int, conn=Depends(get_conn)):
    """Target of the QR sticker: the plant that stands on this spot right now."""
    if slot not in config.slots():
        raise HTTPException(404)
    pid = plants.slot_occupant(conn, slot)
    if pid is None and request.app.state.public:  # planting is not offered on the public side
        return render(request, "platz_frei.html", slot=slot, pos=config.slots()[slot], active_slot=slot)
    path = f"/pflanze/{pid}/schnell" if pid else f"/pflanze/neu?slot={slot}"
    return RedirectResponse(request.scope.get("root_path", "") + path, status_code=307)


def _quick(request, conn, plant_id, status=200, error=None, form=None):
    p = _plant_or_404(conn, plant_id)
    last = conn.execute("SELECT liters FROM watering ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    box = jobs.last_box_phase(conn) or "Wachstum"
    recipes = {ph: watering.get_recipe(conn, ph) for ph in plants.BOX_PHASES}
    due = [t for t in tasks.due_tasks(conn, datetime.now().date()) if t["plant_id"] == plant_id]
    form = form or {}
    plan = watering.current_recipe(conn, datetime.now().date())
    plan = plan if plan["source"] == "plan" else None
    return render(request, "schnell.html", status, p=p, active_slot=p["slot"], error=error, ok=request.query_params.get("ok"), plan=plan, tags=entries.TAGS,
                  liters=form.get("liters") or (f"{last['liters']:g}" if last else ""), recipes=recipes,
                  rezept=form.get("rezept") or ("plan" if plan else box), due=due, phase=plants.current_phase(conn, plant_id),
                  others=len(plants.occupied_plants(conn, plants.now_ts())) - 1)


@router.get("/pflanze/{plant_id}/schnell")
def quick_page(request: Request, plant_id: int, conn=Depends(get_conn)):
    return _quick(request, conn, plant_id)


@router.post("/pflanze/{plant_id}/schnell/giessen")
def quick_water(request: Request, plant_id: int, liters: str = Form(""), rezept: str = Form("wasser"),
                scope: str = Form("all"), conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    try:
        items = watering.items_for(conn, rezept, datetime.now().date())
        watering.add_watering(conn, ts=plants.now_ts(), liters=plants.parse_decimal(liters), items=items,
                              plant_ids=[plant_id] if scope == "only" else None)
    except ValueError as e:
        return _quick(request, conn, plant_id, 400, str(e), {"liters": liters, "rezept": rezept})
    return redirect(request, f"/pflanze/{plant_id}/schnell?ok=giessen")


@router.get("/qr")
def qr_sheet(request: Request):
    urls = qr.slot_urls(request.app.state.options, request.app.state.ha, request.app.state.public_secret)
    labels = [{"slot": s, "pos": config.slots()[s], "url": urls[s], "svg": qr.qr_svg(urls[s])} for s in sorted(urls)]
    return render(request, "qr.html", labels=labels)


@router.get("/kiosk")
def kiosk(request: Request, conn=Depends(get_conn)):
    ha = request.app.state.ha
    data = cockpit.build(ha, conn, request.app.state.options, datetime.now())
    box = config.state(ha, "phase") or jobs.last_box_phase(conn)
    return render(request, "kiosk.html", live=live_values(ha, box), now=datetime.now().strftime("%H:%M"), **data)
