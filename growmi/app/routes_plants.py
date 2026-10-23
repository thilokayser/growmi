from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response

from . import calc, config, entries, events, phase_link, plants, strains, tasks
from .web import get_conn, redirect, remove_photo_files, render, snapshot_before
from .i18n import tr

router = APIRouter()


def _plant_or_404(conn, plant_id: int):
    p = conn.execute("SELECT * FROM plant WHERE id=?", (plant_id,)).fetchone()
    if p is None:
        raise HTTPException(404)
    return p


def _safe_back(back: str, default: str = "/") -> str:
    return back if back.startswith("/") and not back.startswith("//") else default


# --- neue Pflanze -----------------------------------------------------------

def _new_ctx(conn, form=None, error=None):
    form = form or {}
    free = [s for s in config.slots() if plants.slot_occupant(conn, s) is None]
    return {"form": form, "error": error, "strains": strains.list_strains(conn), "phases": plants.PHASES[:3], "free_slots": free,
            "slot": int(form.get("slot") or 0), "eingesetzt_am": form.get("eingesetzt_am") or plants.now_ts()}


@router.get("/pflanze/neu")
def new_form(request: Request, slot: int = 0, conn=Depends(get_conn)):
    return render(request, "plant_new.html", **_new_ctx(conn, {"slot": slot}))


@router.post("/pflanze/neu")
def new_post(request: Request, sorte: str = Form(""), hersteller: str = Form(""), keimdatum: str = Form(""),
             slot: int = Form(...), phase: str = Form("Keimling"), topf: str = Form(""), notiz: str = Form(""),
             eingesetzt_am: str = Form(""), vorlage: str = Form(""), typ: str = Form(""), conn=Depends(get_conn)):
    form = dict(sorte=sorte, hersteller=hersteller, keimdatum=keimdatum, slot=slot, phase=phase, topf=topf,
                notiz=notiz, eingesetzt_am=eingesetzt_am, typ=typ)
    try:
        template = strains.get_strain(conn, int(vorlage)) if vorlage.strip().isdigit() else None
        if not sorte.strip() and template:  # nothing typed: take the saved template
            sorte, hersteller = template["sorte"], hersteller.strip() or template["hersteller"]
            typ = typ or template["typ"] or ""
        if not sorte.strip():
            raise ValueError(tr("Bitte eine Sorte angeben"))
        plants.add_plant(conn, sorte=sorte.strip(), hersteller=hersteller.strip(),
                         keimdatum=plants.norm_date(keimdatum), slot=slot, phase=phase, topf=topf,
                         notiz=notiz, eingesetzt_am=plants.norm_ts(eingesetzt_am), typ=typ)
        strains.ensure_strain(conn, sorte, hersteller, typ)
    except (ValueError, plants.SlotTaken) as e:
        return render(request, "plant_new.html", 400, **_new_ctx(conn, form, str(e)))
    return redirect(request)


# --- Detail -------------------------------------------------------------------

def _detail(request, conn, plant_id, status=200, error=None):
    p = _plant_or_404(conn, plant_id)
    phases = conn.execute("SELECT id, phase, ab FROM plant_phase WHERE plant_id=? ORDER BY ab, id", (plant_id,))
    all_entries = entries.list_entries(conn, plant_id)
    journal = [{"ts": e["ts"], "text": e["body"].strip()} for e in all_entries
               if e["kind"] == "intervention" and e["art"] == "Notiz"]
    from datetime import date
    return render(request, "plant.html", status, p=p, journal=journal[:5], tags=entries.TAGS,
                  phase_suggestion=phase_link.suggestion(conn, request.app.state.ha, date.today()), back=f"/pflanze/{plant_id}", plant_tasks=tasks.plant_tasks(conn, plant_id),
                  zelt_events=events.list_events(conn, 20, p["eingesetzt_am"]), phases=phases.fetchall(),
                  current=plants.current_phase(conn, plant_id), entries=all_entries,
                  totals=calc.plant_totals(conn, plant_id), all_phases=plants.PHASES[:4], now=plants.now_ts(),
                  error=error)


@router.get("/pflanze/{plant_id}")
def detail(request: Request, plant_id: int, conn=Depends(get_conn)):
    return _detail(request, conn, plant_id)


@router.post("/pflanze/{plant_id}/phase")
def change_phase(request: Request, plant_id: int, phase: str = Form(...), ab: str = Form(""),
                 conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    try:
        if phase == "Geerntet":
            raise ValueError(tr("Zum Ernten bitte »Ausziehen« benutzen"))
        plants.set_phase(conn, plant_id, phase, plants.norm_ts(ab))
    except ValueError as e:
        return _detail(request, conn, plant_id, 400, str(e))
    return redirect(request, f"/pflanze/{plant_id}")


@router.post("/pflanze/{plant_id}/ausziehen")
def finish(request: Request, plant_id: int, ts: str = Form(""), trocken_g: str = Form(""),
           nass_g: str = Form(""), conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    try:
        plants.finish_plant(conn, plant_id, plants.norm_ts(ts),
                            plants.parse_decimal(trocken_g) if trocken_g.strip() else None,
                            plants.parse_decimal(nass_g) if nass_g.strip() else None)
    except ValueError as e:
        return _detail(request, conn, plant_id, 400, str(e))
    return redirect(request)


@router.post("/pflanze/{plant_id}/phase/{phase_id}/loeschen")
def phase_delete(request: Request, plant_id: int, phase_id: int, conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    snapshot_before(request, "phase-loeschen")
    owner = conn.execute("SELECT plant_id FROM plant_phase WHERE id=?", (phase_id,)).fetchone()
    if owner is None or owner["plant_id"] != plant_id:
        raise HTTPException(404)
    try:
        plants.delete_phase(conn, phase_id)
    except ValueError as e:
        return _detail(request, conn, plant_id, 400, str(e))
    return redirect(request, f"/pflanze/{plant_id}")


@router.post("/pflanze/{plant_id}/gewicht")
def set_weights(request: Request, plant_id: int, trocken_g: str = Form(""), nass_g: str = Form(""),
                conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    try:
        plants.update_plant(conn, plant_id,
                            trocken_g=plants.parse_decimal(trocken_g) if trocken_g.strip() else None,
                            nass_g=plants.parse_decimal(nass_g) if nass_g.strip() else None)
    except ValueError as e:
        return _detail(request, conn, plant_id, 400, str(e))
    return redirect(request, f"/pflanze/{plant_id}")


def _rating(v: str, name: str) -> int | None:
    if not v.strip():
        return None
    try:
        n = int(v)
    except ValueError:
        raise ValueError(tr("{name}: bitte 1 bis 5 wählen", name=name)) from None
    if not 1 <= n <= 5:
        raise ValueError(tr("{name}: bitte 1 bis 5 wählen", name=name))
    return n


@router.post("/pflanze/{plant_id}/bewertung")
def rate(request: Request, plant_id: int, geschmack: str = Form(""), wirkung: str = Form(""),
         aufwand: str = Form(""), trocknung_tage: str = Form(""), ernte_notiz: str = Form(""),
         conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    try:
        days = None
        if trocknung_tage.strip():
            days = int(trocknung_tage) if trocknung_tage.strip().lstrip("-").isdigit() else -1
            if not 0 <= days <= 365:
                raise ValueError(tr("Trocknungstage: bitte 0 bis 365 eingeben"))
        plants.update_plant(conn, plant_id, bew_geschmack=_rating(geschmack, "Geschmack"),
                            bew_wirkung=_rating(wirkung, "Wirkung"), bew_aufwand=_rating(aufwand, "Aufwand"),
                            trocknung_tage=days, ernte_notiz=ernte_notiz.strip() or None)
    except ValueError as e:
        return _detail(request, conn, plant_id, 400, str(e))
    return redirect(request, f"/pflanze/{plant_id}")


@router.post("/pflanze/{plant_id}/notiz")
def journal_note(request: Request, plant_id: int, text: str = Form(""), back: str = Form(""), tag: str = Form(""),
                 conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    if not text.strip():
        return _detail(request, conn, plant_id, 400, tr("Bitte eine Notiz eintippen"))
    try:
        entries.add_intervention(conn, ts=plants.now_ts(), plant_id=plant_id, art="Notiz", text=text.strip(), tag=tag)
    except ValueError as e:
        return _detail(request, conn, plant_id, 400, str(e))
    return redirect(request, _safe_back(back, f"/pflanze/{plant_id}"))


@router.post("/pflanze/{plant_id}/loeschen")
def delete(request: Request, plant_id: int, conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    snapshot_before(request, "pflanze-loeschen")
    for name in plants.delete_plant(conn, plant_id):
        remove_photo_files(request.app.state.data_dir, name)
    return redirect(request)


@router.post("/pflanze/{plant_id}/bearbeiten")
def edit(request: Request, plant_id: int, sorte: str = Form(...), hersteller: str = Form(""),
         keimdatum: str = Form(""), topf: str = Form(""), notiz: str = Form(""), slot: str = Form(""),
         eingesetzt_am: str = Form(""), typ: str = Form(""), conn=Depends(get_conn)):
    _plant_or_404(conn, plant_id)
    try:
        if not sorte.strip():
            raise ValueError(tr("Bitte eine Sorte angeben"))
        if slot.strip():
            plants.move_plant(conn, plant_id, int(slot))
        fields = dict(sorte=sorte.strip(), hersteller=hersteller.strip(),
                      keimdatum=plants.norm_date(keimdatum), topf=topf, notiz=notiz, typ=plants.norm_typ(typ))
        if eingesetzt_am.strip():
            fields["eingesetzt_am"] = plants.norm_ts(eingesetzt_am)
        plants.update_plant(conn, plant_id, **fields)
        strains.ensure_strain(conn, fields["sorte"], fields["hersteller"], fields["typ"])
    except (ValueError, plants.SlotTaken) as e:
        return _detail(request, conn, plant_id, 400, str(e))
    return redirect(request, f"/pflanze/{plant_id}")


# --- Einträge ändern / löschen -----------------------------------------------------

def _entry_or_404(conn, kind: str, entry_id: int):
    if kind not in entries.TABLES:
        raise HTTPException(404)
    row = conn.execute(f"SELECT * FROM {entries.TABLES[kind]} WHERE id=?", (entry_id,)).fetchone()
    if row is None:
        raise HTTPException(404)
    return row


def _entry_ctx(conn, kind, row, back, error=None, checked=None):
    ctx = {"e": row, "kind": kind, "arten": entries.ARTEN, "back": _safe_back(back), "error": error,
           "all_plants": [], "checked": []}
    if kind == "watering":
        ctx["all_plants"] = conn.execute("SELECT id, slot, sorte, ausgezogen_am FROM plant ORDER BY id").fetchall()
        ctx["checked"] = checked if checked is not None else [
            r[0] for r in conn.execute("SELECT plant_id FROM watering_plant WHERE watering_id=?", (row["id"],))]
    return ctx


@router.get("/eintrag/{kind}/{entry_id}")
def entry_form(request: Request, kind: str, entry_id: int, back: str = "/", conn=Depends(get_conn)):
    return render(request, "eintrag.html", **_entry_ctx(conn, kind, _entry_or_404(conn, kind, entry_id), back))


@router.post("/eintrag/{kind}/{entry_id}/bearbeiten")
def entry_edit(request: Request, kind: str, entry_id: int, ts: str = Form(""), liters: str = Form(""),
               ph: str = Form(""), ec: str = Form(""), art: str = Form(""), text: str = Form(""),
               back: str = Form("/"), edit_plants: str = Form(""), plant_ids: list[int] = Form(default=[]),
               conn=Depends(get_conn)):
    row = _entry_or_404(conn, kind, entry_id)
    try:
        if kind == "watering" and edit_plants and not plant_ids:
            raise ValueError(tr("Mindestens eine Pflanze auswählen"))
        fields = {"ts": plants.norm_ts(ts)}
        if kind == "watering":
            fields.update(liters=plants.parse_decimal(liters),
                          ph=plants.parse_decimal(ph) if ph.strip() else None,
                          ec=plants.parse_decimal(ec) if ec.strip() else None)
        elif kind == "intervention":
            fields.update(art=art, text=text)
        entries.update_entry(conn, kind, entry_id, **fields)
        if kind == "watering" and edit_plants:
            entries.set_watering_plants(conn, entry_id, plant_ids)
    except ValueError as e:
        return render(request, "eintrag.html", 400, **_entry_ctx(conn, kind, row, back, str(e), plant_ids))
    return redirect(request, _safe_back(back))


@router.post("/eintrag/{kind}/{entry_id}/loeschen")
def entry_delete(request: Request, kind: str, entry_id: int, back: str = Form("/"), conn=Depends(get_conn)):
    _entry_or_404(conn, kind, entry_id)
    snapshot_before(request, "eintrag-loeschen")
    filename = entries.delete_entry(conn, kind, entry_id)
    if filename:
        remove_photo_files(request.app.state.data_dir, filename)
    return redirect(request, _safe_back(back))
