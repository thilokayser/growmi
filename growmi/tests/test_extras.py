import io
import json
import os
from datetime import datetime, timedelta

import pytest
from PIL import Image

from app import db, entries, jobs, plants, snapshot
from tests.conftest import FakeHA
from tests.test_routes_home import count, seed_plant

NOW = datetime(2026, 10, 22, 10, 0)


def mk(conn, slot=1, keim="2026-09-01"):
    return plants.add_plant(conn, sorte=f"S{slot}", hersteller="", keimdatum=keim, slot=slot, phase="Wachstum",
                            eingesetzt_am=f"{keim}T08:00")


# ---- nightly copy outside the add-on ------------------------------------------------------------

def test_nightly_backup_writes_db_copy_and_json_once_per_day(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    mk(c)
    c.close()
    (tmp_path / "share").mkdir()  # the HA /share mount exists, the add-on creates its own folder in it
    share = tmp_path / "share" / "growmi"
    opts, state = {"backup_dir": str(share)}, {}
    jobs.run_once(path, FakeHA(), NOW.replace(hour=2), state, opts)
    assert not share.exists()  # before 03:00 nothing happens
    jobs.run_once(path, FakeHA(), NOW.replace(hour=3), state, opts)
    jobs.run_once(path, FakeHA(), NOW.replace(hour=4), state, opts)
    dbs = [f for f in os.listdir(share) if f.endswith(".db")]
    assert len(dbs) == 1
    assert json.load(open(share / "growmi-latest.json"))["plant"][0]["sorte"] == "S1"


def test_backup_is_skipped_quietly_when_the_share_is_missing(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    c.close()
    jobs.run_once(path, FakeHA(), NOW.replace(hour=4), {}, {"backup_dir": "/nonexistent-root/growmi"})


def test_snapshot_into_custom_folder_prunes(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    c.close()
    for _ in range(4):
        snapshot.snapshot(path, "nightly", keep=2, folder=str(tmp_path / "out"))
    assert len(os.listdir(tmp_path / "out")) == 2


# ---- photos: weekly reminder and comparison ------------------------------------------------------------

def photo(conn, pid, ts, name):
    entries.add_photo(conn, ts=ts, plant_id=pid, filename=name)


def test_photo_reminders(conn):
    a, b, c = mk(conn, 1), mk(conn, 2), mk(conn, 3, keim="2026-10-20")
    photo(conn, a, "2026-10-10T09:00", "a.jpg")   # 12 days ago
    photo(conn, b, "2026-10-20T09:00", "b.jpg")   # 2 days ago
    msgs = jobs.photo_reminders(conn, NOW, days=7)
    assert len(msgs) == 1 and msgs[0].startswith("Platz 1") and "12 Tagen" in msgs[0]
    assert c  # planted two days ago, never photographed: not due yet
    plants.update_plant(conn, c, eingesetzt_am="2026-10-01T08:00")
    assert any(m.startswith("Platz 3") and "noch kein Foto" in m for m in jobs.photo_reminders(conn, NOW, days=7))


def test_photo_reminder_is_weekly_in_the_daily_message(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    mk(c)
    c.close()
    ha, state = FakeHA(), {}
    opts = {"notify_service": "notify.notify", "water_reminder_days": 99}
    jobs.run_once(path, ha, NOW, state, opts)
    assert any("Foto" in str(d) for _, _, d in ha.service_calls)
    ha.service_calls.clear()
    jobs.run_once(path, ha, NOW + timedelta(days=1), state, opts)
    assert not any("Foto" in str(d) for _, _, d in ha.service_calls)  # reminded yesterday: quiet for a week
    jobs.run_once(path, ha, NOW + timedelta(days=7), state, opts)
    assert any("Foto" in str(d) for _, _, d in ha.service_calls)


def test_photo_comparison_page_groups_by_week(web):
    a, b = seed_plant(web, 1, "Alpha"), seed_plant(web, 2, "Beta")
    c = web.conn()
    photo(c, a, "2026-09-02T09:00", "a1.jpg")   # germination 2026-09-01 -> week 1
    photo(c, a, "2026-09-10T09:00", "a2.jpg")   # week 2
    photo(c, b, "2026-09-11T09:00", "b2.jpg")   # week 2
    c.close()
    r = web.client.get("/fotos")
    t = r.text
    assert r.status_code == 200 and "Alpha" in t and "Beta" in t
    assert "/fotos/t_a1.jpg" in t and "/fotos/t_a2.jpg" in t and "/fotos/t_b2.jpg" in t
    assert t.index("Woche 1") < t.index("Woche 2")


def test_photo_comparison_empty(web):
    assert "Noch keine Fotos" in web.client.get("/fotos").text


def test_height_feature_is_gone_and_old_empty_table_is_dropped(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    c.execute("CREATE TABLE measure(id INTEGER PRIMARY KEY, plant_id INTEGER, ts TEXT, height_cm REAL)")
    c.commit()
    db.init_schema(c)
    assert c.execute("SELECT 1 FROM sqlite_master WHERE name='measure'").fetchone() is None
    c.execute("CREATE TABLE measure(id INTEGER PRIMARY KEY, plant_id INTEGER, ts TEXT, height_cm REAL)")
    c.execute("INSERT INTO measure(plant_id, ts, height_cm) VALUES (1, 'x', 5)")
    c.commit()
    db.init_schema(c)  # never drops data somebody entered
    assert c.execute("SELECT COUNT(*) FROM measure").fetchone()[0] == 1
    c.close()


def test_plant_page_has_no_height_section(web):
    pid = seed_plant(web, 1)
    assert "Höhe messen" not in web.client.get(f"/pflanze/{pid}").text
    assert web.client.post(f"/pflanze/{pid}/hoehe", data={"height_cm": "5"}).status_code == 404
