from datetime import date, timedelta

from . import plants
from .i18n import tr

TAGS = ("Mangel", "Schädling", "Stress", "Hitze", "Schimmel")
FOLLOW_UP_TAGS = ("Mangel", "Schädling")
FOLLOW_UP_DAYS = 5
ARTEN = ("Notiz", "Topping", "LST", "Umtopfen", "Schädling", "Sonstiges")
TABLES = {"watering": "watering", "intervention": "intervention", "photo": "photo"}
EDITABLE = {"watering": {"ts", "liters", "ph", "ec"},
            "intervention": {"ts", "art", "text", "plant_id"},
            "photo": {"ts"}}


def add_intervention(conn, *, ts: str, plant_id: int, art: str, text: str = "", tag: str | None = None) -> int:
    if art not in ARTEN:
        raise ValueError(tr("Unbekannte Art: {art!r}", art=art))
    tag = (tag or "").strip() or None
    if tag and tag not in TAGS:
        raise ValueError(tr("Unbekannter Problem-Tag: {tag!r}", tag=tag))
    plants.require_plants(conn, [plant_id])
    cur = conn.execute("INSERT INTO intervention(ts, plant_id, art, text, tag) VALUES (?,?,?,?,?)",
                       (ts, plant_id, art, text, tag))
    due = date.fromisoformat(ts[:10]) + timedelta(days=FOLLOW_UP_DAYS)
    if tag in FOLLOW_UP_TAGS and due >= date.today():  # a back-filled old entry needs no check-up
        conn.execute("INSERT OR IGNORE INTO task(plant_id, key, title, due) VALUES (?,?,?,?)",
                     (plant_id, f"nachkontrolle-{cur.lastrowid}", tr("Nachkontrolle Mangel: besser geworden?") if tag == "Mangel" else tr("Nachkontrolle Schädling: besser geworden?"), due.isoformat()))
    conn.commit()
    return cur.lastrowid


def add_photo(conn, *, ts: str, plant_id: int, filename: str) -> int:
    plants.require_plants(conn, [plant_id])
    cur = conn.execute("INSERT INTO photo(ts, plant_id, filename) VALUES (?,?,?)", (ts, plant_id, filename))
    conn.commit()
    return cur.lastrowid


def update_entry(conn, kind: str, entry_id: int, **fields) -> None:
    bad = set(fields) - EDITABLE[kind]
    if bad:
        raise ValueError(tr("Nicht änderbar: {bad}", bad=sorted(bad)))
    if kind == "intervention" and "art" in fields and fields["art"] not in ARTEN:
        raise ValueError(tr("Unbekannte Art: {art!r}", art=fields["art"]))
    if "liters" in fields and fields["liters"] <= 0:
        raise ValueError(tr("Liter müssen größer als 0 sein"))
    if "liters" in fields:  # keep every plant's share of the new total, litres and fertilizer
        conn.execute("UPDATE watering_item_plant SET ml=ml*?/(SELECT liters FROM watering WHERE id=?)"
                     " WHERE item_id IN (SELECT id FROM watering_item WHERE watering_id=?)",
                     (fields["liters"], entry_id, entry_id))
        conn.execute("UPDATE watering_plant SET liters=liters*?/(SELECT liters FROM watering WHERE id=?) WHERE watering_id=?",
                     (fields["liters"], entry_id, entry_id))
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE {TABLES[kind]} SET {sets} WHERE id=?", (*fields.values(), entry_id))
    if "liters" in fields:
        conn.execute("UPDATE watering_item SET ml_total=ml_per_l*? WHERE watering_id=?",
                     (fields["liters"], entry_id))
    conn.commit()


def delete_entry(conn, kind: str, entry_id: int) -> str | None:
    filename = None
    if kind == "photo":
        row = conn.execute("SELECT filename FROM photo WHERE id=?", (entry_id,)).fetchone()
        filename = row["filename"] if row else None
    conn.execute(f"DELETE FROM {TABLES[kind]} WHERE id=?", (entry_id,))  # children cascade
    conn.commit()
    return filename


def list_entries(conn, plant_id: int | None = None) -> list[dict]:
    out = []
    for w in conn.execute("SELECT * FROM watering"):
        pids = [r[0] for r in conn.execute(
            "SELECT plant_id FROM watering_plant WHERE watering_id=? ORDER BY plant_id", (w["id"],))]
        items = conn.execute("SELECT produkt, ml_total FROM watering_item WHERE watering_id=?", (w["id"],))
        mix = ", ".join(f"{i['produkt']} {i['ml_total']:g} ml" for i in items)
        out.append({"kind": "watering", "id": w["id"], "ts": w["ts"], "plant_ids": pids,
                    "text": f"{w['liters']:g} L" + (f" · {mix}" if mix else tr(" · nur Wasser"))})
    for i in conn.execute("SELECT * FROM intervention"):
        out.append({"kind": "intervention", "id": i["id"], "ts": i["ts"], "plant_ids": [i["plant_id"]],
                    "text": f"{tr(i['art'])} {i['text']}".strip(), "tag": i["tag"], "art": i["art"], "body": i["text"]})
    for p in conn.execute("SELECT * FROM photo"):
        out.append({"kind": "photo", "id": p["id"], "ts": p["ts"], "plant_ids": [p["plant_id"]],
                    "text": p["filename"]})
    if plant_id is not None:
        out = [e for e in out if plant_id in e["plant_ids"]]
    return sorted(out, key=lambda e: e["ts"], reverse=True)


def set_watering_plants(conn, watering_id: int, plant_ids: list[int]) -> None:
    if not plant_ids:
        raise ValueError(tr("Mindestens eine Pflanze auswählen"))
    total = conn.execute("SELECT liters FROM watering WHERE id=?", (watering_id,)).fetchone()["liters"]
    ids = sorted(set(plant_ids))
    conn.execute("DELETE FROM watering_plant WHERE watering_id=?", (watering_id,))
    conn.executemany("INSERT INTO watering_plant(watering_id, plant_id, liters) VALUES (?,?,?)",
                     [(watering_id, pid, total / len(ids)) for pid in ids])
    for item in conn.execute("SELECT id, ml_total FROM watering_item WHERE watering_id=?", (watering_id,)).fetchall():
        conn.execute("DELETE FROM watering_item_plant WHERE item_id=?", (item["id"],))
        conn.executemany("INSERT INTO watering_item_plant(item_id, plant_id, ml) VALUES (?,?,?)",
                         [(item["id"], pid, item["ml_total"] / len(ids)) for pid in ids])
    conn.commit()
