from datetime import date

from fastapi import APIRouter, Depends, Request

from . import heatmap
from .web import get_conn, render

router = APIRouter()


@router.get("/fotos")
def photo_comparison(request: Request, conn=Depends(get_conn)):
    """One column per plant, one row per week since germination: the first photo of each week."""
    cols, weeks = [], 0
    for p in conn.execute("SELECT * FROM plant WHERE id IN (SELECT plant_id FROM photo) ORDER BY slot, id"):
        start = date.fromisoformat((p["keimdatum"] or p["eingesetzt_am"])[:10])
        by_week: dict[int, str] = {}
        for ph in conn.execute("SELECT ts, filename FROM photo WHERE plant_id=? ORDER BY ts, id", (p["id"],)):
            w = max((date.fromisoformat(ph["ts"][:10]) - start).days // 7 + 1, 1)
            by_week.setdefault(w, ph["filename"])
        weeks = max([weeks, *by_week])
        cols.append({"plant": p, "weeks": by_week})
    return render(request, "fotos.html", cols=cols, weeks=range(1, weeks + 1))


@router.get("/heatmap")
def climate_heatmap(request: Request, conn=Depends(get_conn)):
    return render(request, "heatmap.html", d=heatmap.build(conn), hours=range(24))
