from datetime import date, datetime, timedelta

from . import config
from .i18n import tr

VPD_TARGET = {"Keimling": (0.4, 0.8), "Wachstum": (0.8, 1.2), "Blüte": (1.2, 1.6)}  # same bands as the dashboard card
NIGHT_BAND = (0.5, 0.9)
DAYS = 10


def _points(ha, key: str, start, end) -> list:
    e = config.entity(key)
    return ha.history_points(e, start, end) if e else []


def hourly_means(points: list, day: date) -> dict[int, float]:
    """Time-weighted mean per hour from [(datetime, value)] state changes; hours without data are left out."""
    pts = sorted(points)
    out = {}
    for h in range(24):
        start = datetime(day.year, day.month, day.day, h)
        end = start + timedelta(hours=1)
        known = [v for t, v in pts if t <= start]
        cur, t0 = (known[-1] if known else None), start
        total = covered = 0.0
        for t, v in pts:
            if start < t < end:
                if cur is not None:
                    total += cur * (t - t0).total_seconds()
                    covered += (t - t0).total_seconds()
                cur, t0 = v, t
        if cur is not None:
            total += cur * (end - t0).total_seconds()
            covered += (end - t0).total_seconds()
        if covered >= 900:
            out[h] = total / covered
    return out


def classify(vpd: float, light: bool, phase: str | None) -> int:
    """-1 too humid (VPD below the band), 0 in band, +1 too dry."""
    lo, hi = VPD_TARGET.get(phase or "", VPD_TARGET["Wachstum"]) if light else NIGHT_BAND
    return -1 if vpd < lo else 1 if vpd > hi else 0


def catch_up_hours(conn, ha, now: datetime) -> None:
    from .jobs import on_hours  # late import: jobs imports this module
    for back in range(DAYS - 1, -1, -1):
        day = (now - timedelta(days=back)).date()
        complete = 24 if day < now.date() else now.hour
        have = {r["hour"] for r in conn.execute("SELECT hour FROM climate_hour WHERE day=?", (day.isoformat(),))}
        if all(h in have for h in range(complete)):
            continue
        start = datetime(day.year, day.month, day.day)
        end = start + timedelta(days=1)
        vpd = hourly_means(_points(ha, "vpd", start, end), day)
        temp = hourly_means(_points(ha, "temp", start, end), day)
        rh = hourly_means(_points(ha, "rh", start, end), day)
        light = ha.history_states(config.role_entity("licht"), start, end) if config.role_entity("licht") else []
        for h in range(complete):
            if h in have or h not in vpd:
                continue
            h0 = start + timedelta(hours=h)
            phase = conn.execute("SELECT phase FROM box_phase_change WHERE ts <= ? ORDER BY ts DESC, id DESC LIMIT 1",
                                 (h0.strftime("%Y-%m-%dT%H:%M"),)).fetchone()
            on = int(on_hours(light, h0 + timedelta(hours=1), h0) >= 0.5) if light else None
            conn.execute("INSERT OR REPLACE INTO climate_hour(day, hour, vpd, temp, rh, light, phase) VALUES (?,?,?,?,?,?,?)",
                         (day.isoformat(), h, round(vpd[h], 3), temp.get(h), rh.get(h), on, phase["phase"] if phase else None))
    conn.commit()


def build(conn, days: int = DAYS) -> dict:
    shown = sorted(r[0] for r in conn.execute("SELECT DISTINCT day FROM climate_hour ORDER BY day DESC LIMIT ?", (days,)))
    cells = {}
    for r in conn.execute(f"SELECT * FROM climate_hour WHERE day IN ({','.join('?' * len(shown))})", shown) if shown else []:
        cells[(r["day"], r["hour"])] = {"vpd": r["vpd"], "status": classify(r["vpd"], bool(r["light"]), r["phase"])}
    spots = []
    for h in range(24):
        sts = [c["status"] for (d, hh), c in cells.items() if hh == h]
        off = sum(s != 0 for s in sts)
        if len(sts) >= 3 and off / len(sts) >= 0.6:
            low = sum(s < 0 for s in sts)
            spots.append((h, "feucht" if low >= off - low else "trocken", off, len(sts)))
    weak, i = [], 0
    while i < len(spots):
        j = i
        while j + 1 < len(spots) and spots[j + 1][0] == spots[j][0] + 1 and spots[j + 1][1] == spots[i][1]:
            j += 1
        grp = spots[i:j + 1]
        k, n = round(sum(g[2] for g in grp) / len(grp)), round(sum(g[3] for g in grp) / len(grp))
        word = tr("zu feucht (VPD zu niedrig)") if grp[0][1] == "feucht" else tr("zu trocken (VPD zu hoch)")
        weak.append(tr("Meist {word}: {a:02d}–{b:02d} Uhr ({k} von {n} Tagen)", word=word, a=grp[0][0], b=grp[-1][0] + 1, k=k, n=n))
        i = j + 1
    return {"days": shown, "cells": cells, "weak": weak}
