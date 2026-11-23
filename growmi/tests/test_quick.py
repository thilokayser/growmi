import io
import re

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
    web.client.post("/giessen", data={f"liters_{a}": "3,5", f"liters_{b}": "2", "rezept": "wasser"})
    t = web.client.get(f"/pflanze/{a}/schnell").text
    assert "Alpha" in t and 'value="3.5"' in t
    assert 'capture="environment"' in t and 'action="/foto"' in t and f'action="/pflanze/{a}/notiz"' in t
    assert 'name="scope"' not in t and f'action="/pflanze/{a}/schnell/giessen"' in t
    assert web.client.get("/pflanze/99/schnell").status_code == 404


def test_quick_watering_waters_only_this_plant(web):
    a, b = two(web)
    r = web.client.post(f"/pflanze/{a}/schnell/giessen", data={"liters": "2", "rezept": "wasser"})
    assert r.status_code == 303 and r.headers["location"] == f"/pflanze/{a}/schnell?ok=giessen"
    web.client.post(f"/pflanze/{a}/schnell/giessen", data={"liters": "1,5", "rezept": "wasser", "scope": "all"})  # old forms
    assert waterings(web) == [[a], [a]]


def test_quick_watering_uses_recipe_and_rejects_bad_liters(web):
    a, _ = two(web)
    c = web.conn()
    f = watering.add_fertilizer(c, "Grow", "Compo")
    watering.set_recipe(c, "Wachstum", [(f, 2.0)])
    c.close()
    web.client.post(f"/pflanze/{a}/schnell/giessen", data={"liters": "3", "rezept": "Wachstum"})
    c = web.conn()
    assert c.execute("SELECT ml_total FROM watering_item").fetchone()[0] == 6.0  # 3 L for this plant
    c.close()
    r = web.client.post(f"/pflanze/{a}/schnell/giessen", data={"liters": "0", "rezept": "wasser"})
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


def test_kiosk_toggle_buttons(web):
    assert 'href="/kiosk"' in web.client.get("/cockpit").text
    t = web.client.get("/kiosk").text
    assert 'aria-label="Anzeige-Modus beenden"' in t and 'href="/"' in t


def test_giessen_offers_one_amount_for_all_plants(web):
    two(web)
    assert 'id="all-liters"' in web.client.get("/giessen").text


# ---- watering from the overview ----------------------------------------------------------

def test_overview_card_has_its_own_water_button_and_the_sheet(web):
    a, _ = two(web)
    t = web.client.get("/").text
    assert f'class="water-btn" href="/pflanze/{a}/giessen"' in t and 'id="water-dialog"' in t
    assert "Alle gießen" in t and f'href="/pflanze/{a}"' in t


def test_water_one_plant_from_the_overview_and_undo(web):
    a, b = two(web)
    c = web.conn()
    f = watering.add_fertilizer(c, "Grow", "Compo")
    watering.set_recipe(c, "Wachstum", [(f, 2.0)])
    c.close()
    r = web.client.post(f"/pflanze/{a}/giessen", data={"liters": "2,5", "rezept": "Wachstum", "ph": "6,1"})
    assert r.status_code == 303 and r.headers["location"].startswith("/?gegossen=")
    assert waterings(web) == [[a]]
    c = web.conn()
    assert c.execute("SELECT ml_total FROM watering_item").fetchone()[0] == 5.0
    assert c.execute("SELECT ph FROM watering").fetchone()[0] == 6.1
    c.close()
    home = web.client.get(r.headers["location"]).text
    wid = r.headers["location"].split("=")[1]
    assert f'action="/eintrag/watering/{wid}/loeschen"' in home
    web.client.post(f"/eintrag/watering/{wid}/loeschen", data={"back": "/"})
    assert waterings(web) == []
    assert web.client.post(f"/pflanze/{a}/giessen", data={"liters": "0", "rezept": "wasser"}).status_code == 400
    assert web.client.get(f"/pflanze/{a}/giessen").status_code == 200 and web.client.get("/pflanze/99/giessen").status_code == 404


def test_card_shows_last_amount_and_thirst(web):
    a, b = two(web)
    web.client.post(f"/pflanze/{a}/giessen", data={"liters": "1,5", "rezept": "wasser"})
    t = web.client.get("/").text
    assert "heute gegossen · 1.5 L" in t
    card = lambda pid: re.search(rf'<div class="slot full[^"]*"(?:(?!</div>).)*?/pflanze/{pid}"', t, re.S).group(0)
    assert "thirsty" not in card(a) and "thirsty" in card(b)  # never watered counts as thirsty


def test_bulk_watering_uses_ticked_plants_common_amount_and_recipe(web):
    a, b = two(web)
    c = web.conn()
    f = watering.add_fertilizer(c, "Grow", "Compo")
    watering.set_recipe(c, "Wachstum", [(f, 2.0)])
    c.close()
    r = web.client.post("/giessen", data={f"sel_{a}": "on", f"sel_{b}": "on", "liters_all": "2", f"liters_{b}": "4",
                                           "rezept": "Wachstum"})
    assert r.status_code == 303
    c = web.conn()
    assert dict(c.execute("SELECT plant_id, liters FROM watering_plant")) == {a: 2.0, b: 4.0}
    assert dict(c.execute("SELECT plant_id, ml FROM watering_item_plant")) == {a: 4.0, b: 8.0}  # recipe x own litres
    c.close()
    web.client.post("/giessen", data={f"sel_{a}": "on", "liters_all": "1", "rezept": "wasser"})
    assert waterings(web)[-1] == [a]  # the unticked plant is left out
    assert web.client.post("/giessen", data={"liters_all": "1", "rezept": "wasser", f"sel_{a}": ""}).status_code == 303
    assert web.client.post("/giessen", data={"rezept": "wasser"}).status_code == 400


def test_bulk_form_leaves_plants_watered_today_unticked(web):
    a, b = two(web)
    web.client.post(f"/pflanze/{a}/giessen", data={"liters": "1", "rezept": "wasser"})
    t = web.client.get("/giessen").text
    assert f'name="sel_{a}" checked' not in t
    assert f'name="sel_{b}" checked' in t and "heute schon gegossen" in t
