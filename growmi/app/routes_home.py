import os
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, Response

from . import calc, cockpit, config, entries, heatmap, images, jobs, phase_link, plants, tasks, watering
from .routes_plants import _plant_or_404
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


def last_liters(conn, plant_id: int) -> float | None:
    row = conn.execute("SELECT wp.liters FROM watering_plant wp JOIN watering w ON w.id=wp.watering_id"
                       " WHERE wp.plant_id=? ORDER BY w.ts DESC, w.id DESC LIMIT 1", (plant_id,)).fetchone()
    return row["liters"] if row and row["liters"] else None


def slot_cards(conn, now: datetime, reminder_days: int) -> list[dict]:
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
        since = calc.days_since_water(conn, pid, now.date())
        liters = last_liters(conn, pid)
        photo = conn.execute("SELECT filename FROM photo WHERE plant_id=? ORDER BY ts DESC, id DESC LIMIT 1",
                             (pid,)).fetchone() if p["kreis"] == "foto" else None
        cards.append({**place, "plant": p, "canopy": canopy_pct(age), "phase": plants.current_phase(conn, pid),
                      "photo": photo["filename"] if photo else None,
                      "phase_day": _days(ab, now) + 1, "age_days": age, "week": age // 7 + 1,
                      "water_l": calc.plant_totals(conn, pid).water_l,
                       "water_ago": _ago(since),
                       "last_l_display": f"{liters:.3f}".rstrip("0").rstrip(".") if liters else "",
                       "last_l": f"{liters:g}" if liters else "", "thirsty": since is None or since >= reminder_days})
    return cards


def occupied_now(conn) -> list:
    ids = plants.occupied_plants(conn, plants.now_ts())
    return [conn.execute("SELECT id, slot, sorte FROM plant WHERE id=?", (i,)).fetchone() for i in ids]


def _num(value, digits: int) -> str | None:
    try:
        number = float(value)
        return f"{number:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{number:.0f}"
    except (TypeError, ValueError):
        return None


def live_values(ha, box_phase: str | None, current: dict | None = None) -> dict:
    vpd = _num(config.state(ha, "vpd"), 2)
    band = heatmap.band(box_phase)
    status = None
    if vpd and band:
        status = "ok" if band[0] <= float(vpd) <= band[1] else "warn"
    temp = _num(current["temperature"] if current is not None else config.state(ha, "temp"), 1)
    rh = _num(config.state(ha, "rh"), 0)
    pct = lambda v, lo, hi: round(min(max((float(v) - lo) / (hi - lo), 0), 1) * 100) if v else 0  # bar fill: scale of the gauge
    online = current["online"] if current is not None else config.state(ha, "online")
    return {"phase": box_phase or config.state(ha, "phase") or "–",
            "temp": temp, "rh": rh, "temp_pct": pct(temp, 15, 35), "rh_pct": pct(rh, 0, 100), "vpd_pct": pct(vpd, 0, 2.5),
            "online": None if online is None else online == "on",
            "vpd": vpd, "vpd_status": status,
            "has": {k: bool(config.entity(k)) for k in ("phase", "temp", "rh", "vpd")}}


@router.get("/")
def home(request: Request, gegossen: int | None = None, conn=Depends(get_conn)):
    ha = request.app.state.ha
    now = datetime.now()
    today = now.date()
    reminder_days = jobs.reminder_days(conn, now, request.app.state.options)
    box = config.state(ha, "phase") or jobs.last_box_phase(conn)
    cards = slot_cards(conn, now, reminder_days)
    pw = jobs.phase_week(conn, today)
    status = cockpit.status(ha, conn, now, reminder_days)
    return render(request, "home.html", cards=cards, plant_count=sum(1 for c in cards if c["plant"]),
                  week=pw[1] if pw else None, live=live_values(ha, box, status), undo=_recent_watering(conn, gegossen),
                  due_count=len(tasks.due_tasks(conn, today)), alert_count=len(status["alerts"]), water=water_options(conn),
                  phase_suggestion=phase_link.suggestion(conn, ha, today), back="/")


def _recent_watering(conn, wid: int | None):
    """The watering just logged from the overview, offered for undo for a few minutes."""
    if wid is None:
        return None
    row = conn.execute("SELECT w.id, w.ts, w.liters, p.sorte FROM watering w JOIN watering_plant wp ON wp.watering_id=w.id"
                       " JOIN plant p ON p.id=wp.plant_id WHERE w.id=?", (wid,)).fetchone()
    return row if row and row["ts"] >= (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M") else None


def water_options(conn) -> dict:
    """Recipe choices of a watering form: what each recipe means in ml per litre, and which one is preselected."""
    box = jobs.last_box_phase(conn) or "Wachstum"
    recipes = {ph: watering.get_recipe(conn, ph) for ph in plants.BOX_PHASES}
    plan = watering.current_recipe(conn, date.today())
    plan = plan if plan["source"] == "plan" else None
    mix = {ph: {i.fertilizer_id: i.ml_per_l for i in items} for ph, items in recipes.items()}
    mix["wasser"] = {}
    if plan:
        mix["plan"] = dict(plan["items"])
    ferts = {r["id"]: r["produkt"] for r in conn.execute("SELECT id, produkt FROM fertilizer")}
    return {"recipes": recipes, "plan": plan, "mix": mix, "ferts": ferts, "rezept": "plan" if plan else box}


def _watered_today(conn) -> set[int]:
    return {r[0] for r in conn.execute("SELECT wp.plant_id FROM watering_plant wp JOIN watering w ON w.id=wp.watering_id"
                                       " WHERE substr(w.ts,1,10)=?", (date.today().isoformat(),))}


def _giessen_ctx(conn, form=None, error=None, typed=None, checked=None):
    form = dict(form or {})
    plist = occupied_now(conn)
    current = {p["id"] for p in plist}
    others = [p for p in conn.execute("SELECT id, slot, sorte FROM plant ORDER BY id DESC") if p["id"] not in current]
    water = water_options(conn)
    # a plant is mostly watered the same amount: show its last one as the hint for an own amount
    last = {p["id"]: f"{last_liters(conn, p['id']):g}" for p in [*plist, *others] if last_liters(conn, p["id"])}
    if checked is None:  # whoever was watered alone today stays unticked: no double watering
        done = _watered_today(conn)
        checked = {p["id"] for p in plist if p["id"] not in done}
    ml = form.get("ml") or {}
    return {"ferts": [{"id": i, "produkt": n} for i, n in sorted(water["ferts"].items(), key=lambda t: t[1])],
            "plants": plist, "others": others, "recipes": water["recipes"], "plan": water["plan"],
            "default_rezept": form.get("rezept") or water["rezept"], "form": form, "error": error,
            "ts": form.get("ts") or plants.now_ts(), "last": last, "typed": typed or {}, "ml": ml, "checked": checked,
            "common": form.get("liters_all", ""), "done": _watered_today(conn)}


@router.get("/giessen")
def giessen_form(request: Request, conn=Depends(get_conn)):
    return render(request, "giessen.html", **_giessen_ctx(conn))


@router.post("/giessen")
async def giessen_post(request: Request, rezept: str = Form("wasser"),
                       ph: str = Form(""), ec: str = Form(""), ts: str = Form(""), conn=Depends(get_conn)):
    data = await request.form()
    typed, ml_typed = watering.raw_amounts(data)
    common = str(data.get("liters_all", "")).strip()
    sel = {int(k[4:]) for k in data if k.startswith("sel_") and k[4:].isdigit()}
    form = {"rezept": rezept, "ph": ph, "ec": ec, "ts": ts, "liters_all": common,
            "ml": {f"{p}_{f}": v for (p, f), v in ml_typed.items()}}
    try:
        # ticked plants get their own amount or else the common one; without ticks (old forms) a typed amount means watered
        wanted = {pid: typed.get(pid, "").strip() or common for pid in sel} if sel else typed
        amounts, plant_ml = watering.parse_amounts(wanted, ml_typed)
        items = watering.items_for(conn, rezept, date.today())
        plant_ml = {pid: m or {fid: per_l * amounts[pid] for fid, per_l in items} for pid, m in plant_ml.items()}
        watering.add_watering(conn, ts=plants.norm_ts(ts), liters=0, items=[], plant_liters=amounts, plant_ml=plant_ml,
                              ph=plants.parse_decimal(ph) if ph.strip() else None,
                              ec=plants.parse_decimal(ec) if ec.strip() else None)
    except ValueError as e:
        return render(request, "giessen.html", 400, **_giessen_ctx(conn, form, str(e), typed, sel or None))
    return redirect(request)


def _plant_water_page(request, conn, plant_id, status=200, error=None, form=None):
    p = _plant_or_404(conn, plant_id)
    form = form or {}
    water = water_options(conn)
    return render(request, "giessen_pflanze.html", status, p=p, water=water, error=error, active_slot=p["slot"],
                  rezept=form.get("rezept") or water["rezept"], form=form,
                  liters=form.get("liters") or (f"{last_liters(conn, plant_id):g}" if last_liters(conn, plant_id) else ""))


@router.get("/pflanze/{plant_id}/giessen")
def water_plant_form(request: Request, plant_id: int, conn=Depends(get_conn)):
    return _plant_water_page(request, conn, plant_id)


@router.post("/pflanze/{plant_id}/giessen")
def water_plant(request: Request, plant_id: int, liters: str = Form(""), rezept: str = Form("wasser"),
                ph: str = Form(""), ec: str = Form(""), conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    try:
        wid = watering.add_watering(
            conn, ts=plants.now_ts(), liters=0, items=watering.items_for(conn, rezept, date.today()),
            plant_liters={plant_id: plants.parse_decimal(liters)},
            ph=plants.parse_decimal(ph) if ph.strip() else None, ec=plants.parse_decimal(ec) if ec.strip() else None)
    except ValueError as e:
        return _plant_water_page(request, conn, plant_id, 400, str(e), {"liters": liters, "rezept": rezept, "ph": ph, "ec": ec})
    return redirect(request, f"/?gegossen={wid}")


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
        when = images.exif_time(datei.file) or plants.norm_ts(ts)  # the photo's own time wins, the form time is the fallback
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
