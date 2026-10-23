from datetime import datetime

from app import entries, plants, watering
from app.timeline import layout_bars, layout_markers
from tests.test_routes_home import seed_plant

D = datetime


def test_layout_bars_proportional():
    bars = layout_bars([("Keimling", "2026-10-01T00:00"), ("Wachstum", "2026-10-02T00:00")],
                       D(2026, 10, 1), D(2026, 10, 5), None)
    assert [(b.phase, b.left_pct, b.width_pct) for b in bars] == [("Keimling", 0, 25), ("Wachstum", 25, 75)]


def test_layout_bars_clipped_to_range():
    bars = layout_bars([("Keimling", "2026-10-01T00:00"), ("Wachstum", "2026-10-02T00:00")],
                       D(2026, 10, 2), D(2026, 10, 4), None)
    assert [(b.phase, b.left_pct, b.width_pct) for b in bars] == [("Wachstum", 0, 100)]


def test_layout_open_ended_plant_stops_at_ausgezogen():
    bars = layout_bars([("Wachstum", "2026-10-01T00:00"), ("Geerntet", "2026-10-03T00:00")],
                       D(2026, 10, 1), D(2026, 10, 5), "2026-10-03T00:00")
    assert [(b.phase, b.left_pct, b.width_pct) for b in bars] == [("Wachstum", 0, 50)]


def test_layout_markers_position():
    ms = layout_markers([("2026-10-03T00:00", "💧", "2 L")], D(2026, 10, 1), D(2026, 10, 5))
    assert [(m.left_pct, m.icon) for m in ms] == [(50, "💧")]
    assert layout_markers([("2026-09-01T00:00", "💧", "x")], D(2026, 10, 1), D(2026, 10, 5)) == []


def test_verlauf_shows_plants_and_markers(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    watering.add_watering(c, ts="2026-10-10T09:00", liters=2.0, items=[], plant_ids=[pid])
    entries.add_intervention(c, ts="2026-10-11T09:00", plant_id=pid, art="Topping")
    c.close()
    r = web.client.get("/verlauf?von=2026-09-01&bis=2026-10-31")
    assert r.status_code == 200
    assert "Northern Lights" in r.text and 'data-icon="droplet"' in r.text and 'data-icon="scissors"' in r.text


def test_verlauf_includes_archived_plant(web):
    pid = seed_plant(web, 1, "Alte Sorte")
    c = web.conn()
    plants.finish_plant(c, pid, "2026-10-05T08:00")
    c.close()
    assert "Alte Sorte" in web.client.get("/verlauf?von=2026-09-01&bis=2026-10-31").text


def test_verlauf_bad_dates_fall_back_to_default(web):
    seed_plant(web, 1)
    r = web.client.get("/verlauf?von=quatsch&bis=2026-99-99")
    assert r.status_code == 200 and "Northern Lights" in r.text


def test_verlauf_empty(web):
    r = web.client.get("/verlauf")
    assert r.status_code == 200 and "Noch keine Pflanzen" in r.text


def test_cluster_markers_merges_close_same_icon():
    from app.timeline import Marker, cluster_markers
    ms = [Marker(10, "droplet", "a"), Marker(10.5, "droplet", "b"), Marker(11, "droplet", "c"),
          Marker(11.2, "scissors", "d"), Marker(60, "droplet", "e")]
    out = cluster_markers(ms)
    assert [(m.left_pct, m.icon, m.count) for m in out] == [
        (10, "droplet", 3), (11.2, "scissors", 1), (60, "droplet", 1)]


def test_verlauf_has_text_summary_aria_hidden_track_and_clustered_markers(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    plants.set_phase(c, pid, "Blüte", "2026-10-02T08:00")
    for day in range(10, 16):
        watering.add_watering(c, ts=f"2026-10-{day}T09:00", liters=1.0, items=[], plant_ids=[pid])
    c.close()
    t = web.client.get("/verlauf?von=2026-01-01&bis=2026-12-31").text
    assert "Blüte ab 02.10." in t and 'class="track" aria-hidden="true"' in t
    assert t.count('class="marker"') == 1 and "6×" in t


def test_verlauf_absurd_dates_fall_back(web):
    seed_plant(web, 1)
    for q in ("bis=9999-12-31", "von=0001-01-01", "von=0001-01-01&bis=9999-12-31"):
        r = web.client.get(f"/verlauf?{q}")
        assert r.status_code == 200 and "Northern Lights" in r.text, q
