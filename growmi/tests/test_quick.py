import io

from PIL import Image

from app import entries, qr, tasks, watering
from tests.test_routes_home import count, seed_plant


def two(web):
    return seed_plant(web, 1, "Alpha"), seed_plant(web, 2, "Beta")


def waterings(web):
    c = web.conn()
    rows = [[r[0] for r in c.execute("SELECT plant_id FROM watering_plant WHERE watering_id=? ORDER BY 1", (w["id"],))]
            for w in c.execute("SELECT id FROM watering ORDER BY id")]
    c.close()
    return rows


def test_platz_redirects_to_current_plant_or_planting(web):
    a, _ = two(web)
    r = web.client.get("/platz/1")
    assert r.status_code == 307 and r.headers["location"] == f"/pflanze/{a}/schnell"
    assert web.client.get("/platz/3").headers["location"] == "/pflanze/neu?slot=3"
    assert web.client.get("/platz/9").status_code == 404


def test_quick_page_has_the_big_actions(web):
    a, b = two(web)
    web.client.post("/giessen", data={"liters": "3,5", "rezept": "wasser", "plant_ids": [a, b]})
    t = web.client.get(f"/pflanze/{a}/schnell").text
    assert "Alpha" in t and 'value="3.5"' in t
    assert 'capture="environment"' in t and 'action="/foto"' in t and f'action="/pflanze/{a}/notiz"' in t
    assert 'name="scope"' in t
    assert web.client.get("/pflanze/99/schnell").status_code == 404


def test_quick_watering_scope_all_or_only_this_plant(web):
    a, b = two(web)
    r = web.client.post(f"/pflanze/{a}/schnell/giessen", data={"liters": "2", "rezept": "wasser", "scope": "all"})
    assert r.status_code == 303 and r.headers["location"] == f"/pflanze/{a}/schnell?ok=giessen"
    web.client.post(f"/pflanze/{a}/schnell/giessen", data={"liters": "1,5", "rezept": "wasser", "scope": "only"})
    assert waterings(web) == [[a, b], [a]]


def test_quick_watering_uses_recipe_and_rejects_bad_liters(web):
    a, _ = two(web)
    c = web.conn()
    f = watering.add_fertilizer(c, "Grow", "Compo")
    watering.set_recipe(c, "Wachstum", [(f, 2.0)])
    c.close()
    web.client.post(f"/pflanze/{a}/schnell/giessen", data={"liters": "3", "rezept": "Wachstum", "scope": "all"})
    c = web.conn()
    assert c.execute("SELECT ml_total FROM watering_item").fetchone()[0] == 6.0
    c.close()
    r = web.client.post(f"/pflanze/{a}/schnell/giessen", data={"liters": "0", "rezept": "wasser", "scope": "all"})
    assert r.status_code == 400 and count(web, "watering") == 1


def test_photo_and_note_return_to_the_quick_page(web):
    a, _ = two(web)
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "green").save(buf, "PNG")
    r = web.client.post("/foto", data={"plant_id": a, "back": f"/pflanze/{a}/schnell?ok=foto"},
                        files={"datei": ("a.png", buf.getvalue(), "image/png")})
    assert r.status_code == 303 and r.headers["location"] == f"/pflanze/{a}/schnell?ok=foto"
    r = web.client.post(f"/pflanze/{a}/notiz", data={"text": "Blätter ok", "back": f"/pflanze/{a}/schnell?ok=notiz"})
    assert r.headers["location"] == f"/pflanze/{a}/schnell?ok=notiz"
    assert "Gespeichert" in web.client.get(f"/pflanze/{a}/schnell?ok=foto").text


def test_quick_page_lists_due_tasks(web):
    a, _ = two(web)
    c = web.conn()
    from datetime import date
    tid = tasks.add_custom(c, a, "Netz spannen", date.today())
    c.close()
    t = web.client.get(f"/pflanze/{a}/schnell").text
    assert "Netz spannen" in t and f"/aufgabe/{tid}/erledigt" in t


def test_qr_svg_and_slot_urls(web):
    assert qr.qr_svg("http://x/y").startswith("<svg")
    urls = qr.slot_urls({"ha_url": "http://ha:8123/"}, web.ha)
    assert urls[1] == "http://ha:8123/api/hassio_ingress/abc/platz/1" and len(urls) == 4


def test_qr_print_page(web):
    t = web.client.get("/qr").text
    assert t.count("<svg") >= 4 + 0 and "Platz 3 · hinten links" in t and "/platz/4" in t
    assert 'class="qr-sheet"' in t


def test_kiosk_page_is_nav_free_and_refreshes(web):
    web.ha.states.update({"sensor.growbox_temperatur": "22.8", "sensor.growbox_vpd": "0.94",
                          "input_select.grow_phase": "Wachstum"})
    t = web.client.get("/kiosk").text
    assert 'http-equiv="refresh"' in t and "<nav" not in t and "22.8" in t and "Wachstum" in t


def test_back_values_carry_no_ingress_prefix_because_redirects_add_it(web):
    a, _ = two(web)
    t = web.client.get(f"/pflanze/{a}/schnell", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"}).text
    assert 'name="back" value="/pflanze/' in t and 'value="/api/hassio_ingress' not in t
    r = web.client.post(f"/pflanze/{a}/notiz", data={"text": "x", "back": f"/pflanze/{a}/schnell?ok=notiz"},
                        headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert r.headers["location"] == f"/api/hassio_ingress/abc/pflanze/{a}/schnell?ok=notiz"
