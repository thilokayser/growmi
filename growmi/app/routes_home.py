import os
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, Response

from . import calc, config, entries, images, jobs, phase_link, plants, watering
from .web import get_conn, redirect, render
from .i18n import tr

router = APIRouter()


# tent seen from above: row 1 = back, row 2 = front (the side you stand on); slots count from front left
def slot_pos(slot: int) -> tuple[str, int, int]:
    """Name, grid row and column of a slot: two columns, the first slot front left, rows count up towards the back."""
    rows = -(-config.slot_count() // 2)
    return config.slots()[slot], rows - (slot - 1) // 2, (slot - 1) % 2 + 1


def canopy_pct(age_days: int) -> float:
    """Drawn plant size, 45 % of the spot at germination up to 90 % at ten weeks."""
    return 45 + min(max(age_days, 0), 70) / 70 * 45


def _days(since: str, now: datetime) -> int:
    return (now - datetime.fromisoformat(since[:16] if "T" in since else since + "T00:00")).days


def _ago(days: int | None) -> str:
    if days is None:
        return tr("noch nie gegossen")
    return {0: tr("heute gegossen"), 1: tr("gestern gegossen")}.get(days) or tr("vor {n} Tagen gegossen", n=days)


def slot_cards(conn) -> list[dict]:
    now = datetime.now()
    cards = []
    for slot in config.slots():
        pid = plants.slot_occupant(conn, slot)
        pos, row, col = slot_pos(slot)
        place = {"slot": slot, "pos": pos, "row": row, "col": col}
        if pid is None:
            cards.append({**place, "plant": None})
            continue
        p = conn.execute("SELECT * FROM plant WHERE id=?", (pid,)).fetchone()
        ab = conn.execute("SELECT ab FROM plant_phase WHERE plant_id=? ORDER BY ab DESC, id DESC LIMIT 1",
                          (pid,)).fetchone()["ab"]
        age = _days(p["keimdatum"] or p["eingesetzt_am"], now)
        cards.append({**place, "plant": p, "canopy": canopy_pct(age), "phase": plants.current_phase(conn, pid),
                      "phase_day": _days(ab, now) + 1, "age_days": age, "week": age // 7 + 1,
                      "water_l": calc.plant_totals(conn, pid).water_l,
                      "water_ago": _ago(calc.days_since_water(conn, pid, now.date()))})
    return cards


def occupied_now(conn) -> list:
    ids = plants.occupied_plants(conn, plants.now_ts())
    return [conn.execute("SELECT id, slot, sorte FROM plant WHERE id=?", (i,)).fetchone() for i in ids]


def _num(ha, key: str, digits: int) -> str | None:
    try:
        return f"{float(config.state(ha, key)):.{digits}f}".rstrip("0").rstrip(".") if digits else f"{float(config.state(ha, key)):.0f}"
    except (TypeError, ValueError):
        return None


def live_values(ha, box_phase: str | None) -> dict:
    vpd = _num(ha, "vpd", 2)
    band = jobs.VPD_TARGET.get(box_phase or "")
    status = None
    if vpd and band:
        status = "ok" if band[0] <= float(vpd) <= band[1] else "warn"
    return {"phase": box_phase or config.state(ha, "phase") or "–",
            "temp": _num(ha, "temp", 1), "rh": _num(ha, "rh", 0),
            "vpd": vpd, "vpd_status": status,
            "has": {k: bool(config.entity(k)) for k in ("phase", "temp", "rh", "vpd")}}


@router.get("/")
def home(request: Request, conn=Depends(get_conn)):
    box = config.state(request.app.state.ha, "phase") or jobs.last_box_phase(conn)
    return render(request, "home.html", cards=slot_cards(conn), live=live_values(request.app.state.ha, box),
                  phase_suggestion=phase_link.suggestion(conn, request.app.state.ha, date.today()), back="/")


def _giessen_ctx(conn, form=None, error=None, checked=None):
    box = jobs.last_box_phase(conn) or "Wachstum"
    form = dict(form or {})
    last = conn.execute("SELECT liters FROM watering ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    if last and not form.get("liters"):  # watering is mostly the same amount: start from the last one
        form["liters"] = f"{last['liters']:g}"
    recipes = {ph: watering.get_recipe(conn, ph) for ph in plants.BOX_PHASES}
    plist = occupied_now(conn)
    current = {p["id"] for p in plist}
    others = [p for p in conn.execute("SELECT id, slot, sorte FROM plant ORDER BY id DESC") if p["id"] not in current]
    plan = watering.current_recipe(conn, date.today())
    plan = plan if plan["source"] == "plan" else None
    return {"plants": plist, "others": others, "recipes": recipes, "plan": plan,
            "default_rezept": form.get("rezept") or ("plan" if plan else box),
            "form": form, "error": error, "ts": form.get("ts") or plants.now_ts(),
            "checked": checked if checked is not None else [p["id"] for p in plist]}


@router.get("/giessen")
def giessen_form(request: Request, conn=Depends(get_conn)):
    return render(request, "giessen.html", **_giessen_ctx(conn))


@router.post("/giessen")
def giessen_post(request: Request, liters: str = Form(""), rezept: str = Form("wasser"),
                 ph: str = Form(""), ec: str = Form(""), ts: str = Form(""),
                 plant_ids: list[int] = Form(default=[]), conn=Depends(get_conn)):
    form = {"liters": liters, "rezept": rezept, "ph": ph, "ec": ec, "ts": ts}
    try:
        if not plant_ids:
            raise ValueError(tr("Bitte mindestens eine Pflanze auswählen"))
        items = watering.items_for(conn, rezept, date.today())
        watering.add_watering(conn, ts=plants.norm_ts(ts), liters=plants.parse_decimal(liters),
                              items=items, plant_ids=plant_ids,
                              ph=plants.parse_decimal(ph) if ph.strip() else None,
                              ec=plants.parse_decimal(ec) if ec.strip() else None)
    except ValueError as e:
        return render(request, "giessen.html", 400, **_giessen_ctx(conn, form, str(e), plant_ids))
    return redirect(request)


@router.get("/notiz")
def notiz_form(request: Request, conn=Depends(get_conn)):
    return render(request, "notiz.html", plants=occupied_now(conn), arten=entries.ARTEN, tags=entries.TAGS,
                  ts=plants.now_ts(), error=None)


@router.post("/notiz")
def notiz_post(request: Request, plant_id: int | None = Form(None), art: str = Form(""), text: str = Form(""),
               ts: str = Form(""), tag: str = Form(""), conn=Depends(get_conn)):
    try:
        if plant_id is None:
            raise ValueError(tr("Bitte eine Pflanze auswählen"))
        entries.add_intervention(conn, ts=plants.norm_ts(ts), plant_id=plant_id, art=art, text=text, tag=tag)
    except ValueError as e:
        return render(request, "notiz.html", 400, plants=occupied_now(conn), arten=entries.ARTEN, tags=entries.TAGS,
                      ts=ts, error=str(e))
    return redirect(request)


@router.get("/foto")
def foto_form(request: Request, conn=Depends(get_conn)):
    return render(request, "foto.html", plants=occupied_now(conn), ts=plants.now_ts(), error=None)


@router.post("/foto")
def foto_post(request: Request, plant_id: int | None = Form(None), ts: str = Form(""), back: str = Form("/"),
              datei: UploadFile | None = File(None), conn=Depends(get_conn)):
    try:
        if plant_id is None:
            raise ValueError(tr("Bitte eine Pflanze auswählen"))
        plants.require_plants(conn, [plant_id])
        if datei is None:
            raise ValueError(tr("Bitte ein Bild auswählen"))
        when = plants.norm_ts(ts)
        name = images.save_image(request.app.state.data_dir, datei.file)
    except ValueError as e:
        return render(request, "foto.html", 400, plants=occupied_now(conn), ts=ts, error=str(e))
    entries.add_photo(conn, ts=when, plant_id=plant_id, filename=name)
    return redirect(request, back if back.startswith("/") and not back.startswith("//") else "/")


@router.get("/fotos/{name}")
def foto_file(request: Request, name: str):
    folder = os.path.join(request.app.state.data_dir, "photos")
    path = os.path.join(folder, name)
    if os.path.basename(name) != name:
        return Response(status_code=404)
    if not os.path.isfile(path) and name.startswith("t_"):  # thumbnail missing: show the original
        path = os.path.join(folder, name[2:])
    if not os.path.isfile(path):
        return Response(status_code=404)
    return FileResponse(path, media_type="image/jpeg")
