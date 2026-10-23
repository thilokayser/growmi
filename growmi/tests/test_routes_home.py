import io
import os

from PIL import Image

from app import plants, watering


def seed_plant(web, slot, sorte="Northern Lights", phase="Wachstum"):
    c = web.conn()
    pid = plants.add_plant(c, sorte=sorte, hersteller="Sensi", keimdatum="2026-09-01", slot=slot,
                           phase=phase, eingesetzt_am="2026-09-01T08:00")
    c.close()
    return pid


def count(web, table):
    c = web.conn()
    n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    c.close()
    return n


def test_home_shows_four_slots(web):
    seed_plant(web, 1)
    seed_plant(web, 2, "Amnesia Haze")
    r = web.client.get("/")
    assert r.status_code == 200
    assert "Northern Lights" in r.text and "Amnesia Haze" in r.text
    assert r.text.count('class="slot free"') == 2
    assert "Pflanze einsetzen" in r.text


def test_home_water_liters_shown(web):
    seed_plant(web, 1)
    seed_plant(web, 2)
    c = web.conn()
    watering.add_watering(c, ts="2026-10-20T12:00", liters=3.0, items=[])
    c.close()
    assert web.client.get("/").text.count("1.5 L") == 2


def test_giessen_form_preselects_current_box_phase_recipe(web):
    seed_plant(web, 1)
    c = web.conn()
    f = watering.add_fertilizer(c, "Bloom", "BioBizz")
    watering.set_recipe(c, "Blüte", [(f, 2.0)])
    c.execute("INSERT INTO box_phase_change(ts, phase) VALUES ('2026-10-20T08:00', 'Blüte')")
    c.commit()
    c.close()
    r = web.client.get("/giessen")
    assert 'value="Blüte" selected' in r.text
    assert 'value="wasser"' in r.text


def post_giessen(web, **form):
    data = {"liters": "2", "rezept": "wasser", "ts": "2026-10-20T12:00"}
    data.update(form)
    return web.client.post("/giessen", data=data)


def test_post_giessen_comma_decimal(web):
    pid = seed_plant(web, 1)
    r = post_giessen(web, liters="2,5", plant_ids=[pid], ph="6,1")
    assert r.status_code == 303
    c = web.conn()
    row = c.execute("SELECT liters, ph FROM watering").fetchone()
    c.close()
    assert (row["liters"], row["ph"]) == (2.5, 6.1)


def test_post_giessen_uses_recipe_of_chosen_phase(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    f = watering.add_fertilizer(c, "Bloom", "BioBizz")
    watering.set_recipe(c, "Blüte", [(f, 2.0)])
    c.close()
    post_giessen(web, liters="3", rezept="Blüte", plant_ids=[pid])
    c = web.conn()
    assert c.execute("SELECT ml_total FROM watering_item").fetchone()[0] == 6.0
    c.close()


def test_post_giessen_all_unchecked_shows_error(web):
    seed_plant(web, 1)
    r = post_giessen(web)
    assert r.status_code == 400 and "Pflanze" in r.text
    assert count(web, "watering") == 0


def test_post_giessen_bad_liters_shows_error(web):
    pid = seed_plant(web, 1)
    for bad in ("0", "-2", "viel", ""):
        r = post_giessen(web, liters=bad, plant_ids=[pid])
        assert r.status_code == 400
    assert count(web, "watering") == 0


def test_post_giessen_empty_slots_shows_error(web):
    r = post_giessen(web)
    assert r.status_code == 400
    assert count(web, "watering") == 0


def test_post_notiz_creates_intervention(web):
    pid = seed_plant(web, 1)
    r = web.client.post("/notiz", data={"plant_id": pid, "art": "Topping", "text": "oben gekappt",
                                        "ts": "2026-10-20T09:00"})
    assert r.status_code == 303 and count(web, "intervention") == 1


def test_foto_upload_resizes(web):
    pid = seed_plant(web, 1)
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), "green").save(buf, "PNG")
    r = web.client.post("/foto", data={"plant_id": pid, "ts": "2026-10-20T09:00"},
                        files={"datei": ("a.png", buf.getvalue(), "image/png")})
    assert r.status_code == 303
    c = web.conn()
    name = c.execute("SELECT filename FROM photo").fetchone()[0]
    c.close()
    img = Image.open(os.path.join(web.data_dir, "photos", name))
    assert max(img.size) == 1600
    assert web.client.get(f"/fotos/{name}").status_code == 200
    assert web.client.get("/fotos/..%2Fgrowlog.db").status_code == 404


def test_foto_upload_rejects_non_image(web):
    pid = seed_plant(web, 1)
    r = web.client.post("/foto", data={"plant_id": pid}, files={"datei": ("a.txt", b"hallo", "text/plain")})
    assert r.status_code == 400 and count(web, "photo") == 0


def test_links_use_ingress_prefix(web):
    pid = seed_plant(web, 1)
    r = web.client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert f'href="/api/hassio_ingress/abc/pflanze/{pid}"' in r.text
    assert 'href="/api/hassio_ingress/abc/giessen"' in r.text
    r = post_giessen(web, liters="2", plant_ids=[pid])
    assert r.status_code == 303
    r = web.client.post("/giessen", data={"liters": "2", "rezept": "wasser", "plant_ids": [pid]},
                        headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert r.headers["location"] == "/api/hassio_ingress/abc/"


def test_post_giessen_unknown_plant_id_shows_error(web):
    seed_plant(web, 1)
    r = post_giessen(web, plant_ids=[99])
    assert r.status_code == 400 and count(web, "watering") == 0


def test_post_notiz_unknown_or_missing_plant_shows_error(web):
    seed_plant(web, 1)
    r = web.client.post("/notiz", data={"plant_id": 99, "art": "Topping"})
    assert r.status_code == 400 and count(web, "intervention") == 0
    r = web.client.post("/notiz", data={"art": "Topping"})
    assert r.status_code == 400 and "Pflanze" in r.text


def test_foto_without_plant_or_file_shows_german_error(web):
    pid = seed_plant(web, 1)
    r = web.client.post("/foto", data={}, files={"datei": ("a.png", b"x", "image/png")})
    assert r.status_code == 400 and "Pflanze" in r.text
    r = web.client.post("/foto", data={"plant_id": pid})
    assert r.status_code == 400 and "Bild" in r.text


def test_foto_too_many_pixels_shows_error(web, monkeypatch):
    pid = seed_plant(web, 1)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "green").save(buf, "PNG")
    r = web.client.post("/foto", data={"plant_id": pid}, files={"datei": ("a.png", buf.getvalue(), "image/png")})
    assert r.status_code == 400 and "zu groß" in r.text and count(web, "photo") == 0


def test_giessen_form_offers_finished_plants_for_backdated_waterings(web):
    old = seed_plant(web, 1, "Alte Sorte")
    seed_plant(web, 2, "Neue Sorte")
    c = web.conn()
    plants.finish_plant(c, old, "2026-10-10T08:00")
    c.close()
    t = web.client.get("/giessen").text
    assert "Alte Sorte" in t and "ausgezogen" in t
    r = post_giessen(web, ts="2026-10-05T10:00", plant_ids=[old])
    assert r.status_code == 303 and count(web, "watering") == 1
