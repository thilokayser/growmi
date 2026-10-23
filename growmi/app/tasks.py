import uuid
from datetime import date, timedelta
from .i18n import tr

# anchor: keim = Keimdatum, wachstum / bluete = start of that phase; typ: only for photoperiod or autoflower plants
RULES = [
    ("topping", "Topping/LST prüfen (Tag 21)", "keim", 21, "photo"),
    ("topping_auto", "LST prüfen (Tag 21, Autoflower nur sanft)", "keim", 21, "auto"),
    ("umstellen", "Auf Blüte umstellen prüfen (12/12)", "wachstum", 28, "photo"),
    ("entlauben1", "Entlauben (Blüte Tag 21)", "bluete", 21, "photo"),
    ("entlauben2", "Zweites Entlauben (Blüte Tag 42)", "bluete", 42, "photo"),
    ("spuelen", "Spülen beginnen (ca. 10 Tage vor Ernte)", "bluete", 53, "photo"),
    ("ernte", "Ernte-Reife prüfen (Trichome)", "bluete", 63, "photo"),
    ("auto_bluete", "Blütebeginn prüfen (Tag 35)", "keim", 35, "auto"),
    ("auto_spuelen", "Spülen beginnen (Tag 70)", "keim", 70, "auto"),
    ("auto_ernte", "Ernte-Reife prüfen (Tag 85)", "keim", 85, "auto"),
]
LOOKBACK_DAYS = 14  # a plant entered with old dates must not trigger a pile of long-past tasks


def _anchor(conn, plant, anchor: str) -> date | None:
    if anchor == "keim":
        return date.fromisoformat((plant["keimdatum"] or plant["eingesetzt_am"])[:10])
    phase = "Wachstum" if anchor == "wachstum" else "Blüte"
    row = conn.execute("SELECT MIN(ab) FROM plant_phase WHERE plant_id=? AND phase=?", (plant["id"], phase)).fetchone()[0]
    return date.fromisoformat(row[:10]) if row else None


def is_auto(plant) -> bool:
    """Explicit type wins; without one, a name containing 'auto' counts as autoflower."""
    return plant["typ"] == "auto" or (not plant["typ"] and "auto" in (plant["sorte"] or "").lower())


def generate_tasks(conn, today: date) -> None:
    """Creates the phase checklist for plants in the box once a task is due (never again for the same task)."""
    for p in conn.execute("SELECT * FROM plant WHERE ausgezogen_am IS NULL").fetchall():
        wrong = [k for k, _, _, _, t in RULES if (t == "auto") != is_auto(p)]  # rules of the other plant type
        conn.execute(f"DELETE FROM task WHERE plant_id=? AND done_at IS NULL AND key IN ({','.join('?' * len(wrong))})",
                     (p["id"], *wrong))
        for key, title, anchor, days, typ in RULES:
            if (typ == "auto") != is_auto(p):
                continue
            start = _anchor(conn, p, anchor)
            if start is None:
                continue
            due = start + timedelta(days=days)
            if today - timedelta(days=LOOKBACK_DAYS) <= due <= today:
                conn.execute("INSERT OR IGNORE INTO task(plant_id, key, title, due) VALUES (?,?,?,?)",
                             (p["id"], key, title, due.isoformat()))
    conn.commit()


def due_tasks(conn, today: date) -> list:
    return conn.execute(
        "SELECT t.*, p.slot, p.sorte FROM task t JOIN plant p ON p.id=t.plant_id"
        " WHERE t.done_at IS NULL AND t.due <= ? AND p.ausgezogen_am IS NULL ORDER BY t.due, t.id",
        (today.isoformat(),)).fetchall()


def plant_tasks(conn, plant_id: int) -> list:
    return conn.execute("SELECT * FROM task WHERE plant_id=? AND done_at IS NULL ORDER BY due, id", (plant_id,)).fetchall()


def mark_done(conn, task_id: int, ts: str) -> None:
    conn.execute("UPDATE task SET done_at=? WHERE id=?", (ts, task_id))
    conn.commit()


def snooze(conn, task_id: int, days: int, today: date) -> None:
    conn.execute("UPDATE task SET due=? WHERE id=?", ((today + timedelta(days=days)).isoformat(), task_id))
    conn.commit()


def add_custom(conn, plant_id: int, title: str, due: date) -> int:
    if not title.strip():
        raise ValueError(tr("Bitte einen Titel für die Aufgabe eingeben"))
    cur = conn.execute("INSERT INTO task(plant_id, key, title, due) VALUES (?,?,?,?)",
                       (plant_id, f"custom-{uuid.uuid4().hex[:8]}", title.strip(), due.isoformat()))
    conn.commit()
    return cur.lastrowid
