import json
import os
import re
import shutil
import sqlite3
from datetime import datetime


TABLES = ["plant", "plant_phase", "fertilizer", "recipe_item", "strain", "watering", "watering_plant",
          "watering_item", "intervention", "photo", "box_phase_change", "climate_day", "box_event", "task", "recipe_week", "recipe_week_flag", "device_day", "wear", "climate_hour"]


DEFAULT_DIR, LATEST = "/share/growmi", "growmi-latest.json"
KV_KEYS = ("config", "public.secret")  # settings and the QR secret travel with the data, the rest of kv is runtime state


def dump_json(conn) -> str:
    data = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in TABLES}
    data["kv"] = {r["k"]: r["v"] for r in conn.execute("SELECT k, v FROM kv") if r["k"] in KV_KEYS}
    data["_meta"] = {"app": "growmi", "created": datetime.now().isoformat(timespec="seconds")}
    return json.dumps(data, ensure_ascii=False, indent=1)


def mirror_photos(data_dir: str, folder: str) -> int:
    """Copies pictures that are not in the backup folder yet, so a rebuilt HA gets them back; returns how many."""
    src, dst = os.path.join(data_dir, "photos"), os.path.join(folder, "photos")
    if not os.path.isdir(src):
        return 0
    os.makedirs(dst, exist_ok=True)
    return _copy_missing(src, dst)


def _copy_missing(src: str, dst: str) -> int:
    n = 0
    for name in os.listdir(src):
        if os.path.isfile(os.path.join(src, name)) and not os.path.exists(os.path.join(dst, name)):
            shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
            n += 1
    return n


def snapshot(db_path: str, reason: str, keep: int = 50, folder: str | None = None) -> str:
    """Consistent copy of the database into <data>/snapshots before anything gets deleted or overwritten."""
    folder = folder or os.path.join(os.path.dirname(db_path), "snapshots")
    os.makedirs(folder, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", reason.lower()).strip("-")
    path = os.path.join(folder, f"{datetime.now():%Y%m%d-%H%M%S-%f}-{slug}.db")
    src, dst = sqlite3.connect(db_path), sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(f for f in os.listdir(folder) if f.endswith(".db"))[:-keep]:
        os.remove(os.path.join(folder, old))
    return path
