import copy
import io
import json
import os

import pytest

from app import config, db, jobs, plants, restore, snapshot
from tests.conftest import FakeHA


def fill(path, sorte="Alt", slots=("a", "b", "c", "d")):
    c = db.connect(path)
    db.init_schema(c)
    config.save(c, {**config.EXAMPLE, "slots": list(slots)})
    pid = plants.add_plant(c, sorte=sorte, hersteller="H", keimdatum="2026-10-01", slot=1, phase="Wachstum")
    c.execute("INSERT INTO fertilizer(produkt, hersteller) VALUES ('Compo', 'Compo')")
    c.execute("INSERT INTO watering(ts, liters) VALUES ('2026-10-02T08:00', 2.0)")
    c.execute("INSERT INTO watering_plant(watering_id, plant_id) VALUES (1, ?)", (pid,))
    c.execute("INSERT INTO photo(ts, plant_id, filename) VALUES ('2026-10-02T09:00', ?, 'x.jpg')", (pid,))
    c.execute("INSERT OR REPLACE INTO kv(k, v) VALUES ('public.secret', 'old-secret')")
    c.commit()
    return c


def test_dump_contains_kv_and_meta(tmp_path):
    c = fill(str(tmp_path / "a.db"))
    data = json.loads(snapshot.dump_json(c))
    assert "_meta" in data and set(data["kv"]) == {"config", "public.secret"}
    assert json.loads(data["kv"]["config"])["slots"] == ["a", "b", "c", "d"]


@pytest.mark.parametrize("text", ["kein json", "[1, 2]", "{}", '{"unbekannt": []}', '{"plant": "x"}', '{"plant": [1]}'])
def test_parse_rejects_garbage(text):
    with pytest.raises(ValueError):
        restore.parse(text)


def test_parse_accepts_old_format_without_kv():
    parsed = restore.parse('{"plant": [{"id": 1, "sorte": "A", "slot": 1, "eingesetzt_am": "x"}]}')
    assert parsed["kv"] == {} and len(parsed["tables"]["plant"]) == 1


def test_roundtrip_replaces_everything(tmp_path):
    a = fill(str(tmp_path / "a.db"), sorte="Neu", slots=("x", "y"))
    text = snapshot.dump_json(a)
    b = fill(str(tmp_path / "b.db"), sorte="Andere")
    b.execute("INSERT INTO strain(sorte) VALUES ('Nur in B')")
    b.commit()
    counts = restore.apply(b, str(tmp_path / "b.db"), restore.parse(text))
    assert counts["plant"] == 1
    assert json.loads(snapshot.dump_json(b))["plant"] == json.loads(text)["plant"]
    assert json.loads(snapshot.dump_json(b))["strain"] == json.loads(text)["strain"]
    assert b.execute("PRAGMA foreign_key_check").fetchall() == []
    assert config.slot_names() == ["x", "y"]
    assert any(f.endswith("vor-restore.db") for f in os.listdir(tmp_path / "snapshots"))


def test_failure_rolls_back(tmp_path):
    b = fill(str(tmp_path / "b.db"), sorte="Bleibt")
    bad = restore.parse('{"plant": [{"id": 9, "slot": 1}]}')  # NOT NULL columns missing
    with pytest.raises(ValueError):
        restore.apply(b, str(tmp_path / "b.db"), bad)
    assert b.execute("SELECT sorte FROM plant").fetchone()["sorte"] == "Bleibt"


def test_photo_mirror_and_restore(tmp_path):
    data, share, fresh = tmp_path / "data", tmp_path / "share", tmp_path / "fresh"
    (data / "photos").mkdir(parents=True)
    (data / "photos" / "a.jpg").write_bytes(b"1")
    (data / "photos" / "t_a.jpg").write_bytes(b"2")
    assert snapshot.mirror_photos(str(data), str(share)) == 2
    assert snapshot.mirror_photos(str(data), str(share)) == 0
    assert restore.restore_photos(str(share / "photos"), str(fresh)) == 2
    assert (fresh / "photos" / "a.jpg").read_bytes() == b"1"
    assert restore.restore_photos(str(share / "photos"), str(fresh)) == 0


def test_nightly_mirrors_photos(tmp_path):
    from datetime import datetime
    path = str(tmp_path / "x.db")
    c = fill(path)
    c.close()
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "p.jpg").write_bytes(b"1")
    (tmp_path / "share").mkdir()
    share = tmp_path / "share" / "growmi"
    jobs.run_once(path, FakeHA(), datetime(2026, 10, 22, 4, 0), {}, {"backup_dir": str(share)})
    assert (share / "photos" / "p.jpg").exists() and (share / "growmi-latest.json").exists()


UPLOAD = lambda text: {"datei": ("sicherung.json", io.BytesIO(text.encode()), "application/json")}


def test_web_flow(web, tmp_path):
    a = fill(str(tmp_path / "src.db"), sorte="AusSicherung", slots=("p", "q"))
    text = snapshot.dump_json(a)
    assert web.client.get("/wiederherstellen").status_code == 200
    r = web.client.post("/wiederherstellen/pruefen", data={"quelle": "upload"}, files=UPLOAD(text))
    assert r.status_code == 200 and "AusSicherung" not in r.text and "plant" in r.text
    r = web.client.post("/wiederherstellen/ausfuehren", data={})
    assert r.status_code == 400
    r = web.client.post("/wiederherstellen/ausfuehren", data={"bestaetigt": "on"})
    assert r.status_code == 303
    assert web.conn().execute("SELECT sorte FROM plant").fetchone()["sorte"] == "AusSicherung"
    assert config.slot_names() == ["p", "q"]


def test_web_rejects_bad_file(web):
    r = web.client.post("/wiederherstellen/pruefen", data={"quelle": "upload"}, files=UPLOAD("kaputt"))
    assert r.status_code == 400


def test_execute_without_pending_is_400(web):
    assert web.client.post("/wiederherstellen/ausfuehren", data={"bestaetigt": "on"}).status_code == 400


def test_public_twin_404(pub):
    assert pub.client.get("/s/secret123/wiederherstellen").status_code == 404
    assert pub.client.post("/s/secret123/wiederherstellen/ausfuehren", data={"bestaetigt": "on"}).status_code == 404


def test_server_check_rejects_unknown_number(web):
    assert web.client.post("/wiederherstellen/pruefen", data={"quelle": "server", "nr": "7"}).status_code == 400
