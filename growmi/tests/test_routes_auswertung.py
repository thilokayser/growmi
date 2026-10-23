from app import plants, watering
from tests.test_routes_home import seed_plant


def test_auswertung_empty_db_ok(web):
    r = web.client.get("/auswertung")
    assert r.status_code == 200 and "Noch keine Pflanzen" in r.text


def test_auswertung_groups_by_sorte(web):
    seed_plant(web, 1, "Amnesia Haze")
    seed_plant(web, 2, "Blue Dream")
    t = web.client.get("/auswertung").text
    assert t.count('class="sorte-group"') == 2
    assert t.index("Amnesia Haze") < t.index("Blue Dream")


def test_auswertung_missing_values_shown_as_dash(web):
    seed_plant(web, 1)
    r = web.client.get("/auswertung")
    assert r.status_code == 200 and "–" in r.text


def test_auswertung_two_runs_same_strain_side_by_side(web):
    a = seed_plant(web, 1, "Amnesia Haze")
    c = web.conn()
    plants.finish_plant(c, a, "2026-10-01T08:00", trocken_g=20.0)
    plants.add_plant(c, sorte="Amnesia Haze", hersteller="H", keimdatum="2026-10-02", slot=1,
                     phase="Keimling", eingesetzt_am="2026-10-02T08:00")
    c.close()
    t = web.client.get("/auswertung").text
    assert t.count('class="sorte-group"') == 1
    assert t.count("<tr class=\"plant\"") == 2


def test_auswertung_shows_values(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    f = watering.add_fertilizer(c, "Bloom", "BioBizz")
    watering.add_watering(c, ts="2026-10-20T12:00", liters=5.0, items=[(f, 4.0)], plant_ids=[pid])
    plants.update_plant(c, pid, trocken_g=10.0)
    c.close()
    t = web.client.get("/auswertung").text
    for needle in ("10 g", "5 L", "Bloom", "20 ml", "2 g/L", "0.5 g/ml"):
        assert needle in t
