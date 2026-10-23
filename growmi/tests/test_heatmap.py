from datetime import date, datetime, timedelta

import pytest

from app import db, heatmap
from tests.conftest import FakeHA

DAY = date(2026, 10, 21)
SW = "switch.grow_light"


def at(h, m=0, day=DAY):
    return datetime(day.year, day.month, day.day, h, m)


def test_hourly_means_time_weighted_and_gaps():
    pts = [(at(0), 1.0), (at(5, 30), 0.5)]
    m = heatmap.hourly_means(pts, DAY)
    assert m[0] == pytest.approx(1.0) and m[5] == pytest.approx(0.75) and m[6] == pytest.approx(0.5)
    assert heatmap.hourly_means([], DAY) == {}
    late = heatmap.hourly_means([(at(10), 2.0)], DAY)
    assert 9 not in late and late[10] == pytest.approx(2.0)  # nothing known before the first reading


def test_value_known_from_before_the_day_carries_into_it():
    m = heatmap.hourly_means([(at(23, 0, DAY - timedelta(days=1)), 0.8), (at(3), 1.0)], DAY)
    assert m[0] == pytest.approx(0.8) and m[3] == pytest.approx(1.0)


def test_classify_uses_phase_band_by_day_and_night_band():
    assert heatmap.classify(0.9, True, "Wachstum") == 0
    assert heatmap.classify(0.5, True, "Wachstum") == -1 and heatmap.classify(1.4, True, "Wachstum") == 1
    assert heatmap.classify(1.3, True, "Blüte") == 0
    assert heatmap.classify(0.7, False, "Wachstum") == 0
    assert heatmap.classify(0.3, False, "Wachstum") == -1 and heatmap.classify(1.0, False, None) == 1
    assert heatmap.classify(0.9, True, None) == 0  # unknown phase: growth band


def feed(ha, vpd=0.9, light_on=True):
    ha.point_histories["sensor.growbox_vpd"] = [(at(0), vpd)]
    ha.point_histories["sensor.growbox_temperatur"] = [(at(0), 23.0)]
    ha.point_histories["sensor.growbox_luftfeuchtigkeit"] = [(at(0), 66.0)]
    ha.state_histories[SW] = [(at(0), "on" if light_on else "off")]


def test_catch_up_fills_complete_hours_once(conn):
    conn.execute("INSERT INTO box_phase_change(ts, phase) VALUES ('2026-10-01T08:00', 'Wachstum')")
    ha = FakeHA()
    feed(ha)
    heatmap.catch_up_hours(conn, ha, datetime(2026, 10, 22, 10, 30))
    rows = conn.execute("SELECT * FROM climate_hour WHERE day='2026-10-21'").fetchall()
    assert len(rows) == 24 and rows[0]["vpd"] == pytest.approx(0.9) and rows[0]["light"] == 1 and rows[0]["phase"] == "Wachstum"
    today = conn.execute("SELECT COUNT(*) FROM climate_hour WHERE day='2026-10-22'").fetchone()[0]
    assert today <= 10  # only hours that are over (0..9 at 10:30)
    n = conn.execute("SELECT COUNT(*) FROM climate_hour").fetchone()[0]
    heatmap.catch_up_hours(conn, ha, datetime(2026, 10, 22, 10, 30))
    assert conn.execute("SELECT COUNT(*) FROM climate_hour").fetchone()[0] == n


def test_catch_up_ignores_missing_sensor_data(conn):
    heatmap.catch_up_hours(conn, FakeHA(), datetime(2026, 10, 22, 10, 30))
    assert conn.execute("SELECT COUNT(*) FROM climate_hour").fetchone()[0] == 0


def fill(conn, hours_low=(), light=1):
    for d in range(1, 6):
        day = f"2026-10-{d:02d}"
        for h in range(24):
            vpd = 0.4 if h in hours_low else 0.9
            conn.execute("INSERT INTO climate_hour(day, hour, vpd, temp, rh, light, phase) VALUES (?,?,?,?,?,?,?)",
                         (day, h, vpd, 23.0, 66.0, light, "Wachstum"))
    conn.commit()


def test_weak_spots_group_hours_and_name_the_direction(conn):
    fill(conn, hours_low=(2, 3, 4))
    data = heatmap.build(conn, 10)
    assert len(data["days"]) == 5
    assert any("02–05 Uhr" in w and "zu feucht" in w and "5 von 5" in w for w in data["weak"])


def test_no_weak_spots_when_everything_is_in_band(conn):
    fill(conn)
    assert heatmap.build(conn, 10)["weak"] == []


def test_heatmap_page(web):
    c = web.conn()
    fill(c, hours_low=(2, 3, 4))
    c.close()
    t = web.client.get("/heatmap").text
    assert 'class="heatmap"' in t and t.count('class="hm hm-low"') >= 15 and "hm-ok" in t
    assert "zu feucht" in t and "02–05 Uhr" in t
    assert 'href="/heatmap"' in web.client.get("/cockpit").text


def test_heatmap_page_empty(web):
    assert "Noch keine Stundenwerte" in web.client.get("/heatmap").text


def test_run_once_collects_hours(tmp_path):
    from app import jobs
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    c.close()
    ha = FakeHA()
    feed(ha)
    jobs.run_once(path, ha, datetime(2026, 10, 22, 10, 30), {}, {})
    c = db.connect(path)
    assert c.execute("SELECT COUNT(*) FROM climate_hour").fetchone()[0] >= 24
    c.close()
