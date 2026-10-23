from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Request

from . import climate, entries, events
from .timeline import cluster_markers, layout_bars, layout_markers
from .web import get_conn, render
from .i18n import tr

router = APIRouter()
ICONS = {"Notiz": "note", "Topping": "scissors", "LST": "link", "Umtopfen": "package", "Schädling": "bug", "Sonstiges": "note"}


def _date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


@router.get("/verlauf")
def verlauf(request: Request, von: str | None = None, bis: str | None = None, conn=Depends(get_conn)):
    plants_ = conn.execute("SELECT * FROM plant ORDER BY eingesetzt_am, id").fetchall()
    if not plants_:
        return render(request, "verlauf.html", rows=[], von="", bis="")
    today = date.today()
    first = date.fromisoformat(plants_[0]["eingesetzt_am"][:10])
    d_von, d_bis = _date(von) or first, _date(bis) or today
    if d_bis < d_von or (d_bis - d_von).days > 3660 or d_von.year < 2000:
        d_von, d_bis = first, today
    start, end = datetime.combine(d_von, time.min), datetime.combine(d_bis + timedelta(days=1), time.min)
    rows = []
    for p in plants_:
        phases = [(r["phase"], r["ab"]) for r in
                  conn.execute("SELECT phase, ab FROM plant_phase WHERE plant_id=? ORDER BY ab, id", (p["id"],))]
        items = []
        for e in entries.list_entries(conn, p["id"]):
            if e["kind"] == "watering":
                items.append((e["ts"], "droplet", e["text"]))
            elif e["kind"] == "intervention":
                items.append((e["ts"], ICONS.get(e["text"].split(" ")[0], "note"), e["text"]))
        waterings = sum(1 for e in items if e[1] == "droplet")
        summary = " · ".join(tr("{phase} ab {day}.{month}.", phase=tr(ph), day=ab[8:10], month=ab[5:7]) for ph, ab in phases)
        if waterings:
            summary += tr(" · {n}× Gießen", n=waterings)
        rows.append({"plant": p, "bars": layout_bars(phases, start, end, p["ausgezogen_am"]),
                     "markers": cluster_markers(layout_markers(items, start, end)), "summary": summary})
    start_day, end_day = d_von.isoformat(), d_bis.isoformat()
    charts = []
    for column, title, unit in (("t_avg", tr("Temperatur Ø pro Tag"), "°C"), ("vpd_avg", tr("VPD Ø pro Tag"), "kPa")):
        series = climate.daily_series(conn, start_day, end_day, column)
        if len(series) >= 2:
            vals = [v for _, v in series]
            charts.append({"title": title, "unit": unit, "points": climate.polyline(vals, 300, 80),
                           "min": min(vals), "max": max(vals), "first": series[0][0], "last": series[-1][0]})
    now_pct = layout_markers([(datetime.now().strftime("%Y-%m-%dT%H:%M"), "", "")], start, end)
    return render(request, "verlauf.html", rows=rows, von=d_von.isoformat(), bis=d_bis.isoformat(),
                  today_pct=now_pct[0].left_pct if now_pct else None,
                  first=first.isoformat(), today=today.isoformat(), charts=charts,
                  zelt_events=events.list_events(conn, 30))
