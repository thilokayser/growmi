import math
import sqlite3
from datetime import datetime

from . import config
from .i18n import tr

PHASES = ("Keimling", "Wachstum", "Blüte", "Trocknung", "Geerntet")
BOX_PHASES = ("Keimling", "Wachstum", "Blüte")
EDITABLE = {"sorte", "hersteller", "keimdatum", "topf", "notiz", "eingesetzt_am",
            "ausgezogen_am", "trocken_g", "nass_g", "bew_geschmack", "bew_wirkung", "bew_aufwand",
            "trocknung_tage", "ernte_notiz", "typ"}


TYPEN = {"auto": "Autoflower", "photo": "Photoperiodisch"}


def norm_typ(typ: str | None) -> str | None:
    typ = (typ or "").strip()
    if typ and typ not in TYPEN:
        raise ValueError(tr("Typ: bitte Autoflower oder Photoperiodisch wählen"))
    return typ or None


class SlotTaken(Exception):
    pass


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def norm_ts(s: str) -> str:
    """Blank -> now; otherwise 'YYYY-MM-DDTHH:MM' (seconds are dropped)."""
    if not s.strip():
        return now_ts()
    try:
        return datetime.strptime(s.strip()[:16], "%Y-%m-%dT%H:%M").strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        raise ValueError(tr("Ungültige Zeit: {s!r}", s=s)) from None


def norm_date(s: str) -> str | None:
    if not s.strip():
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(tr("Ungültiges Datum: {s!r}", s=s)) from None


def parse_decimal(s: str, allow_zero: bool = False) -> float:
    """'2,5' -> 2.5; rejects text, zero (unless allowed) and negatives (form input from a phone)."""
    try:
        v = float(str(s).strip().replace(",", "."))
    except ValueError:
        raise ValueError(tr("Keine Zahl: {s!r}", s=s)) from None
    if not math.isfinite(v) or v < 0 or (v == 0 and not allow_zero):
        raise ValueError(tr("Zahl muss größer als 0 sein: {s!r}", s=s))
    return v


def _check_phase(phase: str) -> None:
    if phase not in PHASES:
        raise ValueError(tr("Unbekannte Phase: {phase!r}", phase=phase))


def require_plants(conn, plant_ids: list[int]) -> None:
    marks = ",".join("?" * len(plant_ids))
    found = conn.execute(f"SELECT COUNT(*) FROM plant WHERE id IN ({marks})", plant_ids).fetchone()[0]
    if found != len(set(plant_ids)):
        raise ValueError(tr("Pflanze existiert nicht mehr, bitte Seite neu laden"))


def _check_slot(slot) -> None:
    if slot not in config.slots():
        raise ValueError(tr("Platz muss 1 bis {n} sein: {slot!r}", n=config.slot_count(), slot=slot))


def slot_occupant(conn: sqlite3.Connection, slot: int) -> int | None:
    row = conn.execute("SELECT id FROM plant WHERE slot=? AND ausgezogen_am IS NULL", (slot,)).fetchone()
    return row["id"] if row else None


def add_plant(conn, *, sorte: str, hersteller: str, keimdatum: str, slot: int, phase: str,
              topf: str = "", notiz: str = "", eingesetzt_am: str | None = None, typ: str | None = None) -> int:
    _check_slot(slot)
    _check_phase(phase)
    typ = norm_typ(typ)
    if slot_occupant(conn, slot) is not None:
        raise SlotTaken(tr("Platz {slot} ist belegt", slot=slot))
    eingesetzt_am = eingesetzt_am or now_ts()
    cur = conn.execute(
        "INSERT INTO plant(sorte, hersteller, keimdatum, topf, notiz, slot, eingesetzt_am, typ)"
        " VALUES (?,?,?,?,?,?,?,?)", (sorte, hersteller, keimdatum, topf, notiz, slot, eingesetzt_am, typ))
    pid = cur.lastrowid
    conn.execute("INSERT INTO plant_phase(plant_id, phase, ab) VALUES (?,?,?)", (pid, phase, eingesetzt_am))
    conn.commit()
    return pid


def set_phase(conn, plant_id: int, phase: str, ab: str) -> None:
    _check_phase(phase)
    conn.execute("INSERT INTO plant_phase(plant_id, phase, ab) VALUES (?,?,?)", (plant_id, phase, ab))
    conn.commit()


def current_phase(conn, plant_id: int) -> str:
    row = conn.execute("SELECT phase FROM plant_phase WHERE plant_id=? ORDER BY ab DESC, id DESC LIMIT 1",
                       (plant_id,)).fetchone()
    return row["phase"]


def finish_plant(conn, plant_id: int, ts: str, trocken_g: float | None = None,
                 nass_g: float | None = None) -> None:
    conn.execute("UPDATE plant SET ausgezogen_am=?, trocken_g=COALESCE(?, trocken_g),"
                 " nass_g=COALESCE(?, nass_g) WHERE id=?", (ts, trocken_g, nass_g, plant_id))
    conn.execute("INSERT INTO plant_phase(plant_id, phase, ab) VALUES (?,?,?)", (plant_id, "Geerntet", ts))
    conn.commit()


def occupied_plants(conn, at: str) -> list[int]:
    rows = conn.execute("SELECT id FROM plant WHERE eingesetzt_am <= ? AND"
                        " (ausgezogen_am IS NULL OR ausgezogen_am > ?) ORDER BY id", (at, at))
    return [r["id"] for r in rows]


def update_plant(conn, plant_id: int, **fields) -> None:
    bad = set(fields) - EDITABLE
    if bad:
        raise ValueError(tr("Nicht änderbar: {bad}", bad=sorted(bad)))
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE plant SET {sets} WHERE id=?", (*fields.values(), plant_id))
        conn.commit()


def delete_plant(conn, plant_id: int) -> list[str]:
    """Removes the plant with phases, interventions and photos; returns photo filenames to delete on disk.
    Waterings that covered only this plant go too; shared ones stay (their water share shifts to the rest)."""
    files = [r["filename"] for r in conn.execute("SELECT filename FROM photo WHERE plant_id=?", (plant_id,))]
    conn.execute("DELETE FROM plant WHERE id=?", (plant_id,))
    conn.execute("DELETE FROM watering WHERE id NOT IN (SELECT watering_id FROM watering_plant)")
    conn.commit()
    return files


def move_plant(conn, plant_id: int, slot: int) -> None:
    _check_slot(slot)
    active = conn.execute("SELECT ausgezogen_am IS NULL FROM plant WHERE id=?", (plant_id,)).fetchone()[0]
    if active and slot_occupant(conn, slot) not in (None, plant_id):
        raise SlotTaken(tr("Platz {slot} ist belegt", slot=slot))
    conn.execute("UPDATE plant SET slot=? WHERE id=?", (slot, plant_id))
    conn.commit()


def delete_phase(conn, phase_id: int) -> None:
    row = conn.execute("SELECT plant_id FROM plant_phase WHERE id=?", (phase_id,)).fetchone()
    n = conn.execute("SELECT COUNT(*) FROM plant_phase WHERE plant_id=?", (row["plant_id"],)).fetchone()[0]
    if n <= 1:
        raise ValueError(tr("Mindestens eine Phase muss bleiben"))
    conn.execute("DELETE FROM plant_phase WHERE id=?", (phase_id,))
    conn.commit()
