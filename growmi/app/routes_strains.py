from fastapi import APIRouter, Depends, Form, HTTPException, Request

from . import strains
from .routes_fertilizer import _stammdaten
from .web import get_conn, redirect, render, snapshot_before

router = APIRouter()


def _strain_or_404(conn, strain_id: int):
    s = strains.get_strain(conn, strain_id)
    if s is None:
        raise HTTPException(404)
    return s


@router.post("/stammdaten/sorte")
def strain_add(request: Request, sorte: str = Form(""), hersteller: str = Form(""), notiz: str = Form(""),
               typ: str = Form(""), conn=Depends(get_conn)):
    try:
        strains.add_strain(conn, sorte, hersteller, notiz, typ)
    except ValueError as e:
        return _stammdaten(request, conn, 400, str(e), strain_form=dict(sorte=sorte, hersteller=hersteller, notiz=notiz, typ=typ))
    return redirect(request, "/stammdaten")


@router.get("/stammdaten/sorte/{strain_id}")
def strain_form(request: Request, strain_id: int, conn=Depends(get_conn)):
    return render(request, "sorte.html", s=_strain_or_404(conn, strain_id), error=None)


@router.post("/stammdaten/sorte/{strain_id}/bearbeiten")
def strain_edit(request: Request, strain_id: int, sorte: str = Form(""), hersteller: str = Form(""),
                notiz: str = Form(""), typ: str = Form(""), conn=Depends(get_conn)):
    s = _strain_or_404(conn, strain_id)
    try:
        strains.update_strain(conn, strain_id, sorte=sorte, hersteller=hersteller, notiz=notiz, typ=typ)
    except ValueError as e:
        return render(request, "sorte.html", 400, s=s, error=str(e))
    return redirect(request, "/stammdaten")


@router.post("/stammdaten/sorte/{strain_id}/loeschen")
def strain_delete(request: Request, strain_id: int, conn=Depends(get_conn)):
    _strain_or_404(conn, strain_id)
    snapshot_before(request, "sorte-loeschen")
    strains.delete_strain(conn, strain_id)
    return redirect(request, "/stammdaten")
