import io
import os
import sqlite3

import pytest
from PIL import Image

from app import db, plants, watering
from app.web import fmt_npk
from tests.test_routes_home import count, seed_plant


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), "blue").save(buf, "PNG")
    return buf.getvalue()


def add(web, **extra):
    data = {"produkt": "Compo Grow", "hersteller": "Compo", "n": "3,5", "p": "1", "k": "0", **extra}
    files = {"datei": ("d.png", png(), "image/png")} if data.pop("with_image", True) else None
    return web.client.post("/stammdaten/duenger", data=data, files=files)


def row(web):
    c = web.conn()
    r = c.execute("SELECT * FROM fertilizer ORDER BY id DESC LIMIT 1").fetchone()
    c.close()
    return dict(r)


def photo_files(web):
    folder = os.path.join(web.data_dir, "photos")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def test_migration_adds_columns_to_existing_database(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE fertilizer(id INTEGER PRIMARY KEY, produkt TEXT NOT NULL, hersteller TEXT NOT NULL DEFAULT '')")
    old.execute("INSERT INTO fertilizer(produkt, hersteller) VALUES ('Bloom', 'BB')")
    old.commit()
    old.close()
    for _ in range(2):  # idempotent
        c = db.connect(path)
        db.init_schema(c)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(fertilizer)")}
        assert {"n", "p", "k", "filename"} <= cols
        assert c.execute("SELECT produkt FROM fertilizer").fetchone()[0] == "Bloom"
        c.close()


def test_fmt_npk():
    assert fmt_npk({"n": 3.5, "p": 1.0, "k": 0.0}) == "3.5-1-0"
    assert fmt_npk({"n": None, "p": None, "k": None}) == ""
    assert fmt_npk({"n": 3.0, "p": None, "k": 5.0}) == "3-?-5"


def test_add_and_update_fertilizer_validate_npk(conn):
    fid = watering.add_fertilizer(conn, "Grow", "Compo", n=3.0, p=1.0, k=4.0)
    row_ = conn.execute("SELECT n, p, k FROM fertilizer WHERE id=?", (fid,)).fetchone()
    assert tuple(row_) == (3.0, 1.0, 4.0)
    for bad in (-1.0, 100.5):
        with pytest.raises(ValueError):
            watering.add_fertilizer(conn, "X", "", n=bad)
        with pytest.raises(ValueError):
            watering.update_fertilizer(conn, fid, k=bad)
    watering.update_fertilizer(conn, fid, produkt="Grow 2", k=None)
    row_ = conn.execute("SELECT produkt, k FROM fertilizer WHERE id=?", (fid,)).fetchone()
    assert tuple(row_) == ("Grow 2", None)
    with pytest.raises(ValueError):
        watering.update_fertilizer(conn, fid, id=7)


def test_parse_decimal_allow_zero():
    assert plants.parse_decimal("0", allow_zero=True) == 0.0
    with pytest.raises(ValueError):
        plants.parse_decimal("-1", allow_zero=True)


def test_add_fertilizer_with_npk_and_image(web):
    r = add(web)
    assert r.status_code == 303
    f = row(web)
    assert (f["produkt"], f["n"], f["p"], f["k"]) == ("Compo Grow", 3.5, 1.0, 0.0)
    assert f["filename"].endswith(".jpg") and photo_files(web) == sorted([f["filename"], f"t_{f['filename']}"])
    page = web.client.get("/stammdaten").text
    assert "3.5-1-0" in page and f"/fotos/t_{f['filename']}" in page and "None" not in page


def test_add_fertilizer_without_npk_or_image(web):
    r = web.client.post("/stammdaten/duenger", data={"produkt": "Bloom"})
    assert r.status_code == 303
    f = row(web)
    assert (f["n"], f["p"], f["k"], f["filename"]) == (None, None, None, None)
    assert "None" not in web.client.get("/stammdaten").text


def test_bad_npk_or_image_rejected_and_nothing_saved(web):
    for bad in ({"n": "abc"}, {"n": "150"}, {"k": "-2"}):
        assert add(web, **bad).status_code == 400
    r = web.client.post("/stammdaten/duenger", data={"produkt": "X"},
                        files={"datei": ("a.txt", b"hallo", "text/plain")})
    assert r.status_code == 400
    assert count(web, "fertilizer") == 0 and photo_files(web) == []


def test_edit_form_prefilled_and_saved_keeping_image(web):
    add(web)
    f = row(web)
    page = web.client.get(f"/stammdaten/duenger/{f['id']}").text
    assert 'value="Compo Grow"' in page and 'value="3.5"' in page
    r = web.client.post(f"/stammdaten/duenger/{f['id']}/bearbeiten",
                        data={"produkt": "Compo Grow Plus", "hersteller": "Compo", "n": "4", "p": "", "k": "0"})
    assert r.status_code == 303
    g = row(web)
    assert (g["produkt"], g["n"], g["p"], g["k"], g["filename"]) == ("Compo Grow Plus", 4.0, None, 0.0, f["filename"])


def test_edit_replace_and_remove_image(web):
    add(web)
    old = row(web)
    base = {"produkt": "Compo Grow", "hersteller": "Compo", "n": "3", "p": "1", "k": "4"}
    web.client.post(f"/stammdaten/duenger/{old['id']}/bearbeiten", data=base,
                    files={"datei": ("n.png", png(), "image/png")})
    new = row(web)
    assert new["filename"] != old["filename"]
    assert photo_files(web) == sorted([new["filename"], f"t_{new['filename']}"])
    web.client.post(f"/stammdaten/duenger/{old['id']}/bearbeiten", data={**base, "remove_bild": "1"})
    assert row(web)["filename"] is None and photo_files(web) == []


def test_edit_does_not_change_old_waterings(web):
    seed_plant(web, 1)
    add(web, with_image=False)
    f = row(web)
    c = web.conn()
    watering.add_watering(c, ts="2026-10-20T12:00", liters=2.0, items=[(f["id"], 2.0)])
    c.close()
    web.client.post(f"/stammdaten/duenger/{f['id']}/bearbeiten", data={"produkt": "Umbenannt"})
    c = web.conn()
    assert c.execute("SELECT produkt FROM watering_item").fetchone()[0] == "Compo Grow"
    c.close()


def test_delete_fertilizer_removes_image_files(web):
    add(web)
    f = row(web)
    assert web.client.post(f"/stammdaten/duenger/{f['id']}/loeschen").status_code == 303
    assert count(web, "fertilizer") == 0 and photo_files(web) == []


def test_unknown_fertilizer_404(web):
    assert web.client.get("/stammdaten/duenger/99").status_code == 404
    assert web.client.post("/stammdaten/duenger/99/bearbeiten", data={"produkt": "x"}).status_code == 404
