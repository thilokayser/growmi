from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from . import images, plants, stock, strains, watering
from .web import get_conn, redirect, remove_photo_files, render, snapshot_before
from .i18n import tr

router = APIRouter()


def _price(preis: str, flasche: str) -> list[float | None]:
    return [plants.parse_decimal(v) if v.strip() else None for v in (preis, flasche)]


def _npk(n: str, p: str, k: str) -> list[float | None]:
    return [plants.parse_decimal(v, allow_zero=True) if v.strip() else None for v in (n, p, k)]


def _stammdaten(request, conn, status=200, error=None, form=None, strain_form=None):
    fert = conn.execute("SELECT * FROM fertilizer ORDER BY produkt").fetchall()
    recipes = {ph: {r.fertilizer_id: r.ml_per_l for r in watering.get_recipe(conn, ph)}
               for ph in plants.BOX_PHASES}
    stocks = {f["id"]: stock.status(conn, f["id"]) for f in fert}
    return render(request, "stammdaten.html", status, fert=fert, recipes=recipes, phases=plants.BOX_PHASES, stocks=stocks,
                  error=error, form=form or {}, strains=strains.list_strains(conn), strain_form=strain_form or {})


def _fert_or_404(conn, fertilizer_id: int):
    f = conn.execute("SELECT * FROM fertilizer WHERE id=?", (fertilizer_id,)).fetchone()
    if f is None:
        raise HTTPException(404)
    return f


@router.get("/stammdaten")
def stammdaten(request: Request, conn=Depends(get_conn)):
    return _stammdaten(request, conn)


@router.post("/stammdaten/duenger")
def fert_add(request: Request, produkt: str = Form(""), hersteller: str = Form(""), n: str = Form(""),
             p: str = Form(""), k: str = Form(""), preis_eur: str = Form(""), flasche_ml: str = Form(""),
             datei: UploadFile | None = File(None), conn=Depends(get_conn)):
    data_dir, name = request.app.state.data_dir, None
    try:
        if not produkt.strip():
            raise ValueError(tr("Bitte ein Produkt angeben"))
        nv, pv, kv = _npk(n, p, k)
        eur, ml = _price(preis_eur, flasche_ml)
        if datei is not None and datei.filename:
            name = images.save_image(data_dir, datei.file)
        fid = watering.add_fertilizer(conn, produkt.strip(), hersteller.strip(), n=nv, p=pv, k=kv, filename=name,
                                      preis_eur=eur, flasche_ml=ml)
        if ml:  # a new bottle: stock starts full
            stock.set_stock(conn, fid, ml)
    except ValueError as e:
        if name:
            remove_photo_files(data_dir, name)
        return _stammdaten(request, conn, 400, str(e), dict(produkt=produkt, hersteller=hersteller, n=n, p=p, k=k,
                                                           preis_eur=preis_eur, flasche_ml=flasche_ml))
    return redirect(request, "/stammdaten")


@router.get("/stammdaten/duenger/{fertilizer_id}")
def fert_form(request: Request, fertilizer_id: int, conn=Depends(get_conn)):
    return render(request, "duenger.html", f=_fert_or_404(conn, fertilizer_id), error=None)


@router.post("/stammdaten/duenger/{fertilizer_id}/bearbeiten")
def fert_edit(request: Request, fertilizer_id: int, produkt: str = Form(""), hersteller: str = Form(""),
              n: str = Form(""), p: str = Form(""), k: str = Form(""), preis_eur: str = Form(""),
              flasche_ml: str = Form(""), bestand_ml: str = Form(""), remove_bild: str = Form(""), datei: UploadFile | None = File(None), conn=Depends(get_conn)):
    f = _fert_or_404(conn, fertilizer_id)
    snapshot_before(request, "duenger-aendern")
    data_dir, new = request.app.state.data_dir, None
    try:
        if not produkt.strip():
            raise ValueError(tr("Bitte ein Produkt angeben"))
        nv, pv, kv = _npk(n, p, k)
        eur, ml = _price(preis_eur, flasche_ml)
        fields = dict(produkt=produkt.strip(), hersteller=hersteller.strip(), n=nv, p=pv, k=kv,
                      preis_eur=eur, flasche_ml=ml)
        if datei is not None and datei.filename:
            new = images.save_image(data_dir, datei.file)
            fields["filename"] = new
        elif remove_bild:
            fields["filename"] = None
        watering.update_fertilizer(conn, fertilizer_id, **fields)
        if bestand_ml.strip():
            stock.set_stock(conn, fertilizer_id, plants.parse_decimal(bestand_ml, allow_zero=True))
    except ValueError as e:
        if new:
            remove_photo_files(data_dir, new)
        return render(request, "duenger.html", 400, f=f, error=str(e))
    if "filename" in fields and f["filename"]:
        remove_photo_files(data_dir, f["filename"])
    return redirect(request, "/stammdaten")


@router.post("/stammdaten/duenger/{fertilizer_id}/loeschen")
def fert_delete(request: Request, fertilizer_id: int, conn=Depends(get_conn)):
    snapshot_before(request, "duenger-loeschen")
    filename = watering.delete_fertilizer(conn, fertilizer_id)
    if filename:
        remove_photo_files(request.app.state.data_dir, filename)
    return redirect(request, "/stammdaten")


@router.post("/stammdaten/rezept/{phase}")
async def recipe_save(request: Request, phase: str, conn=Depends(get_conn)):
    form = await request.form()
    snapshot_before(request, "rezept-aendern")
    try:
        items = [(int(k[3:]), plants.parse_decimal(v)) for k, v in form.items()
                 if k.startswith("ml_") and str(v).strip()]
        watering.set_recipe(conn, phase, items)
    except ValueError as e:
        return _stammdaten(request, conn, 400, str(e))
    return redirect(request, "/stammdaten")
