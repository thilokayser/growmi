"""Brings a backup (growmi-latest.json or an uploaded export) back into the database, plus the pictures."""
import json
import os
import sqlite3

from . import config, snapshot
from .snapshot import KV_KEYS, TABLES
from .i18n import tr


def parse(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError(tr("Die Datei ist kein gültiges JSON")) from None
    if not isinstance(data, dict):
        raise ValueError(tr("Das ist keine Growmi-Sicherung"))
    tables = {t: data[t] for t in TABLES if t in data}
    if not tables:
        raise ValueError(tr("In der Datei steckt keine bekannte Tabelle, das ist keine Growmi-Sicherung"))
    for name, rows in tables.items():
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ValueError(tr("Tabelle {name} ist fehlerhaft", name=name))
    kv = data.get("kv") if isinstance(data.get("kv"), dict) else {}
    return {"tables": tables, "kv": {k: v for k, v in kv.items() if k in KV_KEYS and isinstance(v, str)}}


def summary(conn, parsed: dict) -> list[dict]:
    return [{"table": t, "file": len(rows),
             "now": conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]} for t, rows in parsed["tables"].items()]


def apply(conn, db_path: str, parsed: dict) -> dict[str, int]:
    """Replaces the data tables with the backup's in one transaction; a snapshot is taken first."""
    snapshot.snapshot(db_path, "vor-restore")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")  # rows arrive in table order, not dependency order
    try:
        for t in TABLES:
            conn.execute(f"DELETE FROM {t}")
            rows = parsed["tables"].get(t, [])
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}
            for row in rows:
                keys = [k for k in row if k in cols]
                conn.execute(f"INSERT INTO {t}({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                             [row[k] for k in keys])
        for key, value in parsed["kv"].items():
            conn.execute("INSERT INTO kv(k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError(tr("Die Sicherung ist in sich nicht stimmig (Verweise ins Leere)"))
        conn.commit()
    except (sqlite3.Error, ValueError) as e:
        conn.rollback()
        raise ValueError(tr("Wiederherstellen abgebrochen, nichts wurde verändert: {e}", e=e)) from None
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
    if "config" in parsed["kv"]:
        config.load(conn)
    return {t: len(rows) for t, rows in parsed["tables"].items()}


def restore_photos(src_dir: str, data_dir: str) -> int:
    if not os.path.isdir(src_dir):
        return 0
    dst = os.path.join(data_dir, "photos")
    os.makedirs(dst, exist_ok=True)
    return snapshot._copy_missing(src_dir, dst)
