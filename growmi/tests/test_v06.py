import csv
import io
import os
import sqlite3
from datetime import date, datetime, timedelta

import pytest

from app import calc, climate, db, entries, jobs, plants, snapshot, watering
from tests.conftest import FakeHA
from tests.test_routes_home import count, seed_plant

NOW = datetime(2026, 10, 20, 10, 0)


def ts(days_ago, hour=9):
    return (NOW - timedelta(days=days_ago)).replace(hour=hour).strftime("%Y-%m-%dT%H:%M")


def mkplant(conn, slot=1, since="2026-09-01T08:00", **kw):
    return plants.add_plant(conn, sorte=f"S{slot}", hersteller="H", keimdatum="2026-09-01", slot=slot,
                            phase="Wachstum", eingesetzt_am=since, **kw)


# ---- 1. snapshots + export -------------------------------------------------------------

def test_snapshot_copies_db_and_prunes(tmp_path):
    path = str(tmp_path / "growlog.db")
    c = db.connect(path)
    db.init_schema(c)
    c.execute("INSERT INTO fertilizer(produkt) VALUES ('Bloom')")
    c.commit()
    c.close()
    for _ in range(5):
        snapshot.snapshot(path, "Test Grund!", keep=3)
    files = sorted(os.listdir(tmp_path / "snapshots"))
    assert len(files) == 3 and files[-1].endswith("test-grund.db")
    s = sqlite3.connect(tmp_path / "snapshots" / files[-1])
    assert s.execute("SELECT produkt FROM fertilizer").fetchone()[0] == "Bloom"


def test_destructive_routes_snapshot_first(web):
    web.client.post("/stammdaten/duenger", data={"produkt": "Compo Grow"})
    c = web.conn()
    fid = c.execute("SELECT id FROM fertilizer").fetchone()[0]
    c.close()
    web.client.post(f"/stammdaten/duenger/{fid}/loeschen")
    folder = os.path.join(web.data_dir, "snapshots")
    s = sqlite3.connect(os.path.join(folder, sorted(os.listdir(folder))[0]))
    assert s.execute("SELECT produkt FROM fertilizer").fetchone()[0] == "Compo Grow"


def test_export_json_and_csv(web):
    seed_plant(web, 1)
    r = web.client.get("/export.json")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    d = r.json()
    assert d["plant"][0]["sorte"] == "Northern Lights" and "fertilizer" in d and "strain" in d
    r = web.client.get("/export.csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:3] == ["platz", "sorte", "hersteller"] and rows[1][1] == "Northern Lights"


# ---- 2. watering in one tap -------------------------------------------------------------

def test_giessen_prefills_last_liters(web):
    pid = seed_plant(web, 1)
    web.client.post("/giessen", data={"liters": "3,5", "rezept": "wasser", "plant_ids": [pid]})
    assert 'value="3.5"' in web.client.get("/giessen").text


def test_home_shows_days_since_watering(web):
    a, b = seed_plant(web, 1), seed_plant(web, 2)
    c = web.conn()
    watering.add_watering(c, ts=(datetime.now() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"), liters=1.0,
                          items=[], plant_ids=[a])
    c.close()
    t = web.client.get("/").text
    assert "vor 3 Tagen gegossen" in t and "noch nie gegossen" in t


def test_water_reminders(conn):
    a = mkplant(conn, 1, since=ts(10))
    b = mkplant(conn, 2, since=ts(10))
    c = mkplant(conn, 3, since=ts(2))
    watering.add_watering(conn, ts=ts(5), liters=1.0, items=[], plant_ids=[a])
    watering.add_watering(conn, ts=ts(1), liters=1.0, items=[], plant_ids=[b])
    msgs = jobs.water_reminders(conn, NOW, days=4)
    assert len(msgs) == 1 and msgs[0].startswith("Platz 1") and "5 Tagen" in msgs[0]
    assert c  # planted 2 days ago, never watered: still within the limit


def test_water_reminder_for_never_watered_old_plant(conn):
    mkplant(conn, 1, since=ts(6))
    assert "noch nie" in jobs.water_reminders(conn, NOW, days=4)[0]


def test_run_once_sends_reminder_once_per_day_after_nine(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    mkplant(c, 1, since=ts(10))
    c.close()
    ha, state = FakeHA(), {}
    opts = {"water_reminder_days": 4, "notify_service": "notify.notify"}
    jobs.run_once(path, ha, NOW.replace(hour=8), state, opts)
    assert ha.service_calls == []
    jobs.run_once(path, ha, NOW, state, opts)
    jobs.run_once(path, ha, NOW.replace(minute=30), state, opts)
    assert [(d, s) for d, s, _ in ha.service_calls] == [("persistent_notification", "create"), ("notify", "notify")]


# ---- 3. harvest rating ----------------------------------------------------------------

def test_rating_route_and_auswertung_averages(web):
    a, b = seed_plant(web, 1, "Amnesia"), seed_plant(web, 2, "Amnesia")
    for pid, g in ((a, "4"), (b, "5")):
        r = web.client.post(f"/pflanze/{pid}/bewertung", data={"geschmack": g, "wirkung": "3", "aufwand": "",
                                                              "trocknung_tage": "12", "ernte_notiz": "fruchtig"})
        assert r.status_code == 303
    assert "fruchtig" in web.client.get(f"/pflanze/{a}").text
    t = web.client.get("/auswertung").text
    assert "Geschmack 4.5" in t and "12 Tage" in t


def test_rating_rejects_out_of_range(web):
    pid = seed_plant(web, 1)
    for bad in ({"geschmack": "6"}, {"wirkung": "0"}, {"trocknung_tage": "-1"}, {"aufwand": "x"}):
        assert web.client.post(f"/pflanze/{pid}/bewertung", data=bad).status_code == 400


# ---- 4. climate ------------------------------------------------------------------------

def test_polyline():
    assert climate.polyline([1, 2, 3], 100, 50) == "0,50 50,25 100,0"
    assert climate.polyline([5, 5], 100, 50) == "0,25 100,25"
    assert climate.polyline([1], 100, 50) == ""


def test_climate_summary_vpd_in_target_and_kwh(conn):
    conn.execute("INSERT INTO box_phase_change(ts, phase) VALUES ('2026-10-01T08:00', 'Wachstum')")
    ha = FakeHA(histories={"sensor.growbox_vpd": [0.5, 0.9, 1.0, 1.5], "sensor.growbox_temperatur": [22.0],
                           "sensor.energy": [1.0, 1.5, 3.4]})
    jobs.climate_summary(conn, ha, date(2026, 10, 19), energy_entity="sensor.energy")
    r = conn.execute("SELECT vpd_ok_pct, kwh FROM climate_day").fetchone()
    assert (r["vpd_ok_pct"], r["kwh"]) == (50.0, 2.4)


def test_phase_stats(conn):
    conn.executemany("INSERT INTO climate_day(day, t_avg, rh_avg, vpd_avg, vpd_ok_pct, kwh, box_phase)"
                     " VALUES (?,?,?,?,?,?,?)",
                     [("2026-10-01", 22.0, 60.0, 0.9, 80.0, 2.0, "Wachstum"),
                      ("2026-10-02", 24.0, 62.0, 1.1, 60.0, 3.0, "Wachstum"),
                      ("2026-10-03", 20.0, 50.0, 1.3, 90.0, None, "Blüte")])
    s = {r["phase"]: r for r in climate.phase_stats(conn)}
    assert (s["Wachstum"]["days"], s["Wachstum"]["t_avg"], s["Wachstum"]["ok_pct"], s["Wachstum"]["kwh"]) == (2, 23.0, 70.0, 5.0)
    assert s["Blüte"]["kwh"] is None


def test_verlauf_and_auswertung_show_climate(web):
    seed_plant(web, 1)
    c = web.conn()
    c.executemany("INSERT INTO climate_day(day, t_avg, vpd_avg, vpd_ok_pct, box_phase) VALUES (?,?,?,?,?)",
                  [("2026-10-10", 22.0, 0.9, 80.0, "Wachstum"), ("2026-10-11", 23.0, 1.0, 70.0, "Wachstum")])
    c.commit()
    c.close()
    t = web.client.get("/verlauf?von=2026-10-01&bis=2026-10-31").text
    assert "<polyline" in t and "Temperatur" in t and "VPD" in t
    a = web.client.get("/auswertung").text
    assert "Klima pro Phase" in a and "Wachstum" in a and "75 %" in a


# ---- 5. cost + energy ----------------------------------------------------------------------

def test_fertilizer_price_snapshot_in_watering(conn):
    mkplant(conn, 1)
    f = watering.add_fertilizer(conn, "Grow", "Compo", preis_eur=20.0, flasche_ml=500.0)
    wid = watering.add_watering(conn, ts=ts(1), liters=2.0, items=[(f, 4.0)])
    assert conn.execute("SELECT eur_per_ml FROM watering_item WHERE watering_id=?", (wid,)).fetchone()[0] == pytest.approx(0.04)
    watering.update_fertilizer(conn, f, preis_eur=99.0)
    assert conn.execute("SELECT eur_per_ml FROM watering_item WHERE watering_id=?", (wid,)).fetchone()[0] == pytest.approx(0.04)
    with pytest.raises(ValueError):
        watering.add_fertilizer(conn, "X", "", preis_eur=-1.0)


def test_plant_cost_energy_and_efficiency(conn):
    a = mkplant(conn, 1)
    f = watering.add_fertilizer(conn, "Grow", "Compo", preis_eur=20.0, flasche_ml=500.0)
    watering.add_watering(conn, ts=ts(1), liters=2.0, items=[(f, 4.0)], plant_ids=[a])
    conn.executemany("INSERT INTO climate_day(day, kwh) VALUES (?,?)", [("2026-10-19", 2.4), ("2026-10-20", 3.6)])
    plants.update_plant(conn, a, trocken_g=10.0)
    t = calc.plant_totals(conn, a, strompreis=0.30)
    assert t.fert_eur == pytest.approx(0.32) and t.kwh == pytest.approx(6.0) and t.strom_eur == pytest.approx(1.8)
    assert t.cost_eur == pytest.approx(2.12) and t.g_per_kwh == pytest.approx(10 / 6) and t.eur_per_g == pytest.approx(0.212)


def test_energy_is_shared_between_plants_on_the_box(conn):
    a = mkplant(conn, 1)
    mkplant(conn, 2, since="2026-10-20T00:00")
    conn.executemany("INSERT INTO climate_day(day, kwh) VALUES (?,?)", [("2026-10-19", 2.4), ("2026-10-20", 3.6)])
    assert calc.plant_totals(conn, a).kwh == pytest.approx(2.4 + 1.8)


def test_no_price_or_energy_gives_none(conn):
    a = mkplant(conn, 1)
    watering.add_watering(conn, ts=ts(1), liters=1.0, items=[], plant_ids=[a])
    t = calc.plant_totals(conn, a)
    assert (t.fert_eur, t.kwh, t.strom_eur, t.cost_eur, t.g_per_kwh, t.eur_per_g) == (None,) * 6


def test_fertilizer_form_saves_price_fields(web):
    web.client.post("/stammdaten/duenger", data={"produkt": "Compo Grow", "preis_eur": "12,90", "flasche_ml": "1000"})
    c = web.conn()
    r = c.execute("SELECT preis_eur, flasche_ml FROM fertilizer").fetchone()
    c.close()
    assert (r["preis_eur"], r["flasche_ml"]) == (12.9, 1000.0)
    assert web.client.post("/stammdaten/duenger", data={"produkt": "X", "preis_eur": "abc"}).status_code == 400
    assert "12.9" in web.client.get("/stammdaten").text


def test_power_price_comes_from_ha_helper_with_option_fallback(tmp_path):
    from app.settings import strompreis
    assert strompreis(FakeHA(states={"input_number.growbox_strompreis": "0,31"}), {"strompreis_eur_kwh": 0.5}) == 0.31
    assert strompreis(FakeHA(states={"input_number.growbox_strompreis": "0.31"}), {}) == 0.31
    for bad in (None, "abc", "0.0"):
        assert strompreis(FakeHA(states={"input_number.growbox_strompreis": bad}), {"strompreis_eur_kwh": 0.5}) == 0.5
    assert strompreis(FakeHA(), {}) == 0.0


def test_consumption_handles_meter_resets():
    assert jobs.consumption([1.0, 1.5, 3.4]) == pytest.approx(2.4)
    assert jobs.consumption([14.85, 14.9, 0.1, 1.7]) == pytest.approx(1.75)  # counter dropped to ~0: new reading counts
    assert jobs.consumption([5.0]) is None and jobs.consumption([]) is None


def test_climate_summary_uses_reset_safe_consumption(conn):
    ha = FakeHA(histories={"sensor.growbox_temperatur": [22.0], "sensor.energy": [14.85, 14.9, 0.1, 1.7]})
    jobs.climate_summary(conn, ha, date(2026, 10, 20), energy_entity="sensor.energy")
    assert conn.execute("SELECT kwh FROM climate_day").fetchone()[0] == pytest.approx(1.75)


def test_repair_recomputes_recent_days_once(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    recent = (date.today() - timedelta(days=1)).isoformat()
    c.execute("INSERT INTO climate_day(day, kwh) VALUES (?, 15.5)", (recent,))
    c.execute("DELETE FROM kv WHERE k='fix.kwh.reset'")
    c.commit()
    db.init_schema(c)  # first start with the fix: recent days with energy are dropped and recomputed by the job
    assert c.execute("SELECT COUNT(*) FROM climate_day").fetchone()[0] == 0
    c.execute("INSERT INTO climate_day(day, kwh) VALUES (?, 2.0)", (recent,))
    c.commit()
    db.init_schema(c)  # second start: leaves correct data alone
    assert c.execute("SELECT kwh FROM climate_day").fetchone()[0] == 2.0
    c.close()


def test_cockpit_energy_today_survives_a_reset(web):
    web.ha.histories["sensor.energy"] = [14.85, 14.9, 0.1, 1.7]
    web.client.app.state.options["energy_entity"] = "sensor.energy"
    assert "1.75 kWh" in web.client.get("/cockpit").text
