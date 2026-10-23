from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from . import cockpit, config, events, phase_link, plants, tasks
from .routes_plants import _detail, _plant_or_404, _safe_back
from .web import get_conn, redirect, render
from .i18n import tr

router = APIRouter()


def _page(request, conn, status=200, error=None):
    data = cockpit.build(request.app.state.ha, conn, request.app.state.options, datetime.now())
    return render(request, "cockpit.html", status, error=error, **data)


@router.get("/cockpit")
def cockpit_page(request: Request, conn=Depends(get_conn)):
    return _page(request, conn)


@router.post("/cockpit/ventilator")
def fan_mode(request: Request, modus: str = Form(""), conn=Depends(get_conn)):
    if modus not in cockpit.MODES:
        return _page(request, conn, 400, tr("Unbekannter Modus"))
    if not config.entity("fan_mode") or not request.app.state.ha.call_service(
            "input_select", "select_option", {"entity_id": config.entity("fan_mode"), "option": modus}):
        return _page(request, conn, 502, tr("Home Assistant hat den Modus nicht übernommen"))
    return redirect(request, "/cockpit")


@router.post("/cockpit/abluft")
def exhaust_mode(request: Request, modus: str = Form(""), conn=Depends(get_conn)):
    if modus not in cockpit.EXHAUST_MODES:
        return _page(request, conn, 400, tr("Unbekannter Modus"))
    if not config.entity("exhaust_mode") or not request.app.state.ha.call_service(
            "input_select", "select_option", {"entity_id": config.entity("exhaust_mode"), "option": modus}):
        return _page(request, conn, 502, tr("Home Assistant hat den Modus nicht übernommen"))
    return redirect(request, "/cockpit")


def _task_or_404(conn, task_id: int):
    if conn.execute("SELECT 1 FROM task WHERE id=?", (task_id,)).fetchone() is None:
        raise HTTPException(404)


@router.post("/aufgabe/{task_id}/erledigt")
def task_done(request: Request, task_id: int, back: str = Form("/cockpit"), conn=Depends(get_conn)):
    _task_or_404(conn, task_id)
    tasks.mark_done(conn, task_id, plants.now_ts())
    return redirect(request, _safe_back(back, "/cockpit"))


@router.post("/aufgabe/{task_id}/spaeter")
def task_snooze(request: Request, task_id: int, back: str = Form("/cockpit"), conn=Depends(get_conn)):
    _task_or_404(conn, task_id)
    tasks.snooze(conn, task_id, 1, date.today())
    return redirect(request, _safe_back(back, "/cockpit"))


@router.post("/pflanze/{plant_id}/aufgabe")
def task_add(request: Request, plant_id: int, title: str = Form(""), due: str = Form(""), conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    try:
        day = plants.norm_date(due) or date.today().isoformat()
        tasks.add_custom(conn, plant_id, title, date.fromisoformat(day))
    except ValueError as e:
        return _detail(request, conn, plant_id, 400, str(e))
    return redirect(request, f"/pflanze/{plant_id}")


@router.post("/box/phase")
def box_phase(request: Request, phase: str = Form(""), licht: str = Form(""), back: str = Form("/cockpit"),
              conn=Depends(get_conn)):
    if phase not in plants.BOX_PHASES:
        return _page(request, conn, 400, tr("Unbekannte Phase"))
    if not phase_link.apply(request.app.state.ha, conn, phase, bool(licht), datetime.now()):
        return _page(request, conn, 502, tr("Home Assistant hat die Umstellung nicht übernommen"))
    return redirect(request, _safe_back(back, "/cockpit"))


@router.post("/box/spaeter")
def box_later(request: Request, back: str = Form("/"), conn=Depends(get_conn)):
    phase_link.snooze(conn, date.today())
    return redirect(request, _safe_back(back, "/"))
