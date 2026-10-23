from .plants import BOX_PHASES

SERIES = {"t_avg", "rh_avg", "vpd_avg", "kwh"}


def polyline(values: list[float], w: float = 300, h: float = 80) -> str:
    """SVG points for a line chart of w x h; fewer than two values give no line."""
    n = len(values)
    if n < 2:
        return ""
    lo, hi = min(values), max(values)
    pts = []
    for i, v in enumerate(values):
        y = h - (v - lo) / (hi - lo) * h if hi > lo else h / 2
        pts.append(f"{i / (n - 1) * w:g},{y:g}")
    return " ".join(pts)


def daily_series(conn, start: str, end: str, column: str) -> list[tuple[str, float]]:
    if column not in SERIES:
        raise ValueError(column)
    rows = conn.execute(f"SELECT day, {column} FROM climate_day WHERE day BETWEEN ? AND ? AND {column} IS NOT NULL"
                        " ORDER BY day", (start, end))
    return [(r[0], r[1]) for r in rows]


def phase_stats(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT box_phase AS phase, COUNT(*) AS days, AVG(t_avg) AS t_avg, AVG(rh_avg) AS rh_avg,"
        " AVG(vpd_avg) AS vpd_avg, AVG(vpd_ok_pct) AS ok_pct, SUM(kwh) AS kwh,        (SELECT COUNT(*) FROM box_event e WHERE e.kind='hitze' AND substr(e.ts,1,10) IN        (SELECT day FROM climate_day c2 WHERE c2.box_phase = climate_day.box_phase)) AS hitze FROM climate_day"
        " WHERE box_phase IS NOT NULL GROUP BY box_phase")
    out = [dict(r) for r in rows]
    return sorted(out, key=lambda r: BOX_PHASES.index(r["phase"]) if r["phase"] in BOX_PHASES else 9)
