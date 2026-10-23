from datetime import date, timedelta

from . import config, plants, tasks

BLOOM_DAYS, VEG_DAYS, AUTO_DAYS, GERM_DAYS = 63, 28, 85, 14  # rules of thumb, same as the task checklist


def _day(ts: str) -> date:
    return date.fromisoformat(ts[:10])


def forecast(conn, today: date) -> list[dict]:
    rows = []
    for slot, name in config.slots().items():
        pid = plants.slot_occupant(conn, slot)
        row = {"slot": slot, "pos": name, "plant": None, "phase": None, "harvest": None, "days_left": None,
               "next_start": None}
        if pid is not None:
            p = conn.execute("SELECT * FROM plant WHERE id=?", (pid,)).fetchone()
            phase = plants.current_phase(conn, pid)
            row.update(plant=p, phase=phase)
            if phase in ("Keimling", "Wachstum", "Blüte"):
                if tasks.is_auto(p):
                    harvest = _day(p["keimdatum"] or p["eingesetzt_am"]) + timedelta(days=AUTO_DAYS)
                else:
                    bloom = conn.execute("SELECT MIN(ab) FROM plant_phase WHERE plant_id=? AND phase='Blüte'", (pid,)).fetchone()[0]
                    veg = conn.execute("SELECT MIN(ab) FROM plant_phase WHERE plant_id=? AND phase='Wachstum'", (pid,)).fetchone()[0]
                    start = _day(bloom) if bloom else _day(veg or p["eingesetzt_am"]) + timedelta(days=VEG_DAYS)
                    harvest = start + timedelta(days=BLOOM_DAYS)
                row.update(harvest=harvest, days_left=(harvest - today).days,
                           next_start=harvest - timedelta(days=GERM_DAYS))
        rows.append(row)
    return rows
