import json
from datetime import date, datetime, timedelta

import pytest

from app import calc, db, entries, jobs, planner, plants, report, stock, watering
from tests.conftest import FakeHA
from tests.test_routes_home import count, seed_plant

NOW = datetime(2026, 10, 22, 19, 0)  # a Thursday evening


def mk(conn, slot=1, keim="2026-09-01", phase="Wachstum", typ=None, sorte=None):
    return plants.add_plant(conn, sorte=sorte or f"S{slot}", hersteller="H", keimdatum=keim, slot=slot, phase=phase,
                            eingesetzt_am=f"{keim}T08:00", typ=typ)


def water(conn, ts, liters, items=(), ids=None):
    return watering.add_watering(conn, ts=ts, liters=liters, items=list(items), plant_ids=ids)


# ---------- 1. stock / shopping list -------------------------------------------------------

def test_stock_rest_gaenge_and_low_flag(conn):
    mk(conn)
    f = watering.add_fertilizer(conn, "Grow", "Compo", preis_eur=20.0, flasche_ml=500.0)
    water(conn, "2026-09-30T09:00", 4.0, [(f, 5.0)])  # before the stock date: not counted
    stock.set_stock(conn, f, 500.0, "2026-10-01T08:00")
    for d in (3, 6, 9):
        water(conn, f"2026-10-{d:02d}T09:00", 4.0, [(f, 5.0)])  # 20 ml each
    s = stock.status(conn, f)
    assert s["rest_ml"] == 440 and s["gaenge"] == pytest.approx(22) and s["low"] is False
    stock.set_stock(conn, f, 50.0, "2026-10-10T08:00")
    water(conn, "2026-10-12T09:00", 4.0, [(f, 5.0)])
    s = stock.status(conn, f)
    assert s["rest_ml"] == 30 and s["gaenge"] == pytest.approx(1.5) and s["low"] is True
    assert [x["produkt"] for x in stock.low_items(conn)] == ["Grow"]


def test_stock_unknown_and_new_bottle(conn):
    f = watering.add_fertilizer(conn, "Bloom", "BB", flasche_ml=1000.0)
    assert stock.status(conn, f) is None
    stock.set_stock(conn, f, 100.0, "2026-10-01T08:00")
    stock.add_bottle(conn, f, "2026-10-05T08:00")
    assert stock.status(conn, f)["rest_ml"] == 1100
    g = watering.add_fertilizer(conn, "NoSize", "")
    with pytest.raises(ValueError):
        stock.add_bottle(conn, g, "2026-10-05T08:00")


def test_stock_pages_and_reminder(web):
    seed_plant(web, 1)
    web.client.post("/stammdaten/duenger", data={"produkt": "Compo Grow", "preis_eur": "12,90", "flasche_ml": "1000"})
    c = web.conn()
    fid = c.execute("SELECT id FROM fertilizer").fetchone()[0]
    stock.set_stock(c, fid, 30.0, "2026-10-01T08:00")
    water(c, "2026-10-10T09:00", 4.0, [(fid, 5.0)])
    c.close()
    assert "Rest" in web.client.get("/stammdaten").text
    t = web.client.get("/einkauf").text
    assert "Compo Grow" in t and "12.9" in t
    assert web.client.post(f"/stammdaten/duenger/{fid}/flasche").status_code == 303
    assert "Compo Grow" not in web.client.get("/einkauf").text.split("Einkaufsliste", 1)[1]
    assert web.client.post("/stammdaten/duenger/99/flasche").status_code == 404


def test_new_fertilizer_with_bottle_size_starts_with_full_stock(web):
    web.client.post("/stammdaten/duenger", data={"produkt": "Neu", "flasche_ml": "500"})
    c = web.conn()
    fid = c.execute("SELECT id FROM fertilizer").fetchone()[0]
    c.close()
    assert stock.status(web.conn(), fid)["rest_ml"] == 500


# ---------- 2. weekly report ----------------------------------------------------------------

def test_weekly_report_numbers_and_text(conn):
    a = mk(conn)
    f = watering.add_fertilizer(conn, "Grow", "C", preis_eur=20.0, flasche_ml=500.0)
    water(conn, "2026-10-20T09:00", 4.0, [(f, 5.0)], [a])
    water(conn, "2026-10-01T09:00", 9.0, [], [a])  # outside the 7 days
    conn.executemany("INSERT INTO climate_day(day, kwh, vpd_ok_pct, box_phase) VALUES (?,?,?,?)",
                     [("2026-10-20", 2.0, 80.0, "Wachstum"), ("2026-10-21", 3.0, 60.0, "Wachstum"),
                      ("2026-10-05", 9.0, 10.0, "Wachstum")])
    conn.execute("INSERT INTO box_event(ts, kind, text) VALUES ('2026-10-21T14:00', 'hitze', 'Hitze')")
    conn.commit()
    r = report.weekly(conn, NOW, 0.30)
    assert r["liters"] == 4.0 and r["ok_pct"] == 70.0 and r["hitze"] == 1
    assert r["strom_eur"] == pytest.approx(1.5) and r["fert_eur"] == pytest.approx(0.8)
    txt = report.text(r)
    assert "4 L" in txt and "70 %" in txt and "Hitze" in txt


def test_weekly_report_page_and_sunday_push(web, tmp_path):
    seed_plant(web, 1)
    assert web.client.get("/bericht").status_code == 200
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    mk(c)
    c.close()
    ha, state = FakeHA(), {}
    sunday = datetime(2026, 10, 25, 18, 30)
    jobs.run_once(path, ha, datetime(2026, 10, 24, 18, 30), state, {"notify_service": "notify.notify"})
    assert not any("Wochenbericht" in str(d) for _, _, d in ha.service_calls)
    jobs.run_once(path, ha, sunday, state, {"notify_service": "notify.notify"})
    jobs.run_once(path, ha, sunday + timedelta(minutes=5), state, {"notify_service": "notify.notify"})
    assert sum("Wochenbericht" in str(d) for _, s, d in ha.service_calls if s == "notify") == 1


# ---------- 3. slot planner ----------------------------------------------------------------------

def test_planner_estimates_harvest_and_successor(conn):
    mk(conn, 1, keim="2026-09-01", phase="Wachstum")                     # photo, bloom not started
    b = mk(conn, 2, keim="2026-09-01", phase="Wachstum")
    plants.set_phase(conn, b, "Blüte", "2026-10-01T08:00")
    mk(conn, 3, keim="2026-09-01", typ="auto")
    rows = {r["slot"]: r for r in planner.forecast(conn, date(2026, 10, 22))}
    assert rows[1]["harvest"] == date(2026, 9, 29) + timedelta(days=63)
    assert rows[2]["harvest"] == date(2026, 10, 1) + timedelta(days=63)
    assert rows[3]["harvest"] == date(2026, 9, 1) + timedelta(days=85)
    assert rows[2]["next_start"] == rows[2]["harvest"] - timedelta(days=planner.GERM_DAYS)
    assert rows[4]["plant"] is None and rows[4]["harvest"] is None
    assert rows[2]["days_left"] == (rows[2]["harvest"] - date(2026, 10, 22)).days


def test_planner_page(web):
    seed_plant(web, 1)
    t = web.client.get("/planung").text
    assert "Ernte" in t and "Platz 4" in t and "frei" in t


# ---------- 4. strain ranking ------------------------------------------------------------------------

def test_ranking_by_strain(conn):
    a = mk(conn, 1, sorte="Alpha")
    b = mk(conn, 2, sorte="Alpha")
    c = mk(conn, 3, sorte="Beta")
    for pid, g, ge in ((a, 20.0, 4), (b, 40.0, 5), (c, 50.0, None)):
        plants.update_plant(conn, pid, trocken_g=g, bew_geschmack=ge)
    mk(conn, 4, sorte="Gamma")  # not harvested: not ranked
    rows = calc.ranking(conn, 0.0)
    assert [r["sorte"] for r in rows] == ["Beta", "Alpha"]
    assert rows[1]["n"] == 2 and rows[1]["avg_g"] == 30.0 and rows[1]["avg_bew"] == 4.5 and rows[0]["avg_bew"] is None


def test_ranking_on_auswertung_page(web):
    pid = seed_plant(web, 1, "Alpha")
    c = web.conn()
    plants.update_plant(c, pid, trocken_g=25.0)
    c.close()
    t = web.client.get("/auswertung").text
    assert "Rangliste" in t and "25 g" in t


# ---------- 5. problem tags -----------------------------------------------------------------------------

def test_problem_tag_validation_and_listing(conn):
    a = mk(conn)
    entries.add_intervention(conn, ts="2026-10-20T09:00", plant_id=a, art="Notiz", text="Spinnmilben", tag="Schädling")
    with pytest.raises(ValueError):
        entries.add_intervention(conn, ts="2026-10-20T09:00", plant_id=a, art="Notiz", text="x", tag="Quatsch")
    assert entries.list_entries(conn, a)[0]["tag"] == "Schädling"


def test_problem_page_counts_and_shows_photos(web):
    a = seed_plant(web, 1, "Alpha")
    r = web.client.post(f"/pflanze/{a}/notiz", data={"text": "Blätter gelb", "tag": "Mangel"})
    assert r.status_code == 303
    c = web.conn()
    entries.add_photo(c, ts=plants.now_ts(), plant_id=a, filename="p1.jpg")
    c.close()
    t = web.client.get("/probleme").text
    assert "Alpha" in t and "Mangel" in t and "Blätter gelb" in t and "/fotos/t_p1.jpg" in t
    assert "Blätter gelb" not in web.client.get("/probleme?tag=Schädling").text
    assert web.client.post(f"/pflanze/{a}/notiz", data={"text": "x", "tag": "Quatsch"}).status_code == 400
    r = web.client.post("/notiz", data={"plant_id": a, "art": "Notiz", "text": "Läuse", "tag": "Schädling"})
    assert r.status_code == 303 and "Läuse" in web.client.get("/probleme").text


# ---------- W3 weekly feeding plan ------------------------------------------------------------------------

def test_phase_week_and_plan_beats_phase_recipe(conn):
    conn.execute("INSERT INTO box_phase_change(ts, phase) VALUES ('2026-10-08T08:00', 'Blüte')")
    conn.commit()
    assert jobs.phase_week(conn, date(2026, 10, 22)) == ("Blüte", 3)
    f = watering.add_fertilizer(conn, "Bloom", "BB")
    watering.set_recipe(conn, "Blüte", [(f, 2.0)])
    cur = watering.current_recipe(conn, date(2026, 10, 22))
    assert cur["source"] == "phase" and cur["items"] == [(f, 2.0)]
    watering.set_week_plan(conn, "Blüte", 3, [(f, 4.0)], water_only=False)
    cur = watering.current_recipe(conn, date(2026, 10, 22))
    assert cur["source"] == "plan" and cur["items"] == [(f, 4.0)] and "Woche 3" in cur["label"]
    watering.set_week_plan(conn, "Blüte", 3, [], water_only=True)
    cur = watering.current_recipe(conn, date(2026, 10, 22))
    assert cur["source"] == "plan" and cur["items"] == [] and "Nur Wasser" in cur["label"]
    assert watering.current_recipe(conn, date(2026, 10, 30))["source"] == "phase"  # week 4 has no plan


def test_watering_form_offers_and_uses_the_plan(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    f = watering.add_fertilizer(c, "Bloom", "BB")
    c.execute("INSERT INTO box_phase_change(ts, phase) VALUES (?, 'Blüte')", (plants.now_ts(),))
    c.commit()
    watering.set_week_plan(c, "Blüte", 1, [(f, 4.0)], water_only=False)
    c.close()
    t = web.client.get("/giessen").text
    assert 'value="plan" selected' in t and "Woche 1" in t
    web.client.post("/giessen", data={"liters": "2", "rezept": "plan", "plant_ids": [pid]})
    c = web.conn()
    assert c.execute("SELECT ml_total FROM watering_item").fetchone()[0] == 8.0
    c.close()
    web.client.post(f"/pflanze/{pid}/schnell/giessen", data={"liters": "1", "rezept": "plan", "scope": "all"})
    c = web.conn()
    assert c.execute("SELECT COUNT(*) FROM watering_item").fetchone()[0] == 2
    c.close()


def test_week_plan_page_roundtrip(web):
    web.client.post("/stammdaten/duenger", data={"produkt": "Bloom"})
    c = web.conn()
    fid = c.execute("SELECT id FROM fertilizer").fetchone()[0]
    c.close()
    r = web.client.post("/stammdaten/wochenplan/Blüte", data={f"ml_1_{fid}": "3,5", "wasser_5": "1"})
    assert r.status_code == 303
    c = web.conn()
    assert watering.get_week_plan(c, "Blüte", 1)[0][0].ml_per_l == 3.5
    assert watering.get_week_plan(c, "Blüte", 5) == ([], True)
    assert watering.get_week_plan(c, "Blüte", 2) is None
    c.close()
    t = web.client.get("/stammdaten/wochenplan?phase=Blüte").text
    assert 'value="3.5"' in t and "checked" in t
    assert web.client.post("/stammdaten/wochenplan/Quatsch", data={}).status_code == 400


# ---------- W4 learned watering interval -----------------------------------------------------------------------

def test_learned_interval_sets_reminder_threshold(conn):
    a = mk(conn)
    assert jobs.learned_interval(conn, NOW) is None
    for d in (1, 4, 7, 10, 13, 16, 19):
        water(conn, f"2026-10-{d:02d}T09:00", 1.0, [], [a])
    assert jobs.learned_interval(conn, NOW) == pytest.approx(3.0)
    assert jobs.reminder_days(conn, NOW, {"water_reminder_days": 4}) == 5  # ceil(3 * 1.5)
    assert jobs.reminder_days(conn, NOW, {"water_reminder_days": 4}) >= 2


def test_fixed_threshold_when_too_little_history(conn):
    a = mk(conn)
    water(conn, "2026-10-19T09:00", 1.0, [], [a])
    assert jobs.reminder_days(conn, NOW, {"water_reminder_days": 4}) == 4
    assert jobs.reminder_days(conn, NOW, {}) == 4


# ---------- W2 wear counters -----------------------------------------------------------------------------------------

def test_on_hours_from_state_series():
    t = lambda h: datetime(2026, 10, 21, h, 0)
    series = [(t(0), "on"), (t(6), "off"), (t(8), "on")]
    assert jobs.on_hours(series, datetime(2026, 10, 22, 0, 0)) == pytest.approx(6 + 16)
    assert jobs.on_hours([], datetime(2026, 10, 22)) == 0
    assert jobs.on_hours([(t(0), "unavailable")], datetime(2026, 10, 22)) == 0


def test_device_hours_fill_reset_and_alert(conn):
    ha = FakeHA()
    day = datetime(2026, 10, 21, 0, 0)
    ha.state_histories["switch.grow_light"] = [(day, "on")]
    jobs.catch_up_devices(conn, ha, date(2026, 10, 22))
    jobs.catch_up_devices(conn, ha, date(2026, 10, 22))  # idempotent
    hrs = jobs.device_status(conn, date(2026, 10, 22))
    lamp = next(d for d in hrs if d["key"] == "lampe")
    assert lamp["hours"] == pytest.approx(24.0) and lamp["pct"] < 1
    jobs.set_wear_limit(conn, "lampe", 25.0)
    assert next(d for d in jobs.device_status(conn, date(2026, 10, 22)) if d["key"] == "lampe")["due"] is True
    jobs.reset_wear(conn, "lampe", date(2026, 10, 22))
    assert next(d for d in jobs.device_status(conn, date(2026, 10, 22)) if d["key"] == "lampe")["hours"] == 0
    assert jobs.wear_reminders(conn, date(2026, 10, 22)) == []


def test_wear_page(web):
    t = web.client.get("/verschleiss").text
    assert "Lampe" in t and "Filter" in t
    assert web.client.post("/verschleiss/lampe/getauscht").status_code == 303
    assert web.client.post("/verschleiss/quatsch/getauscht").status_code == 404
    assert web.client.post("/verschleiss/lampe/limit", data={"limit_h": "20000"}).status_code == 303
    assert web.client.post("/verschleiss/lampe/limit", data={"limit_h": "abc"}).status_code == 400


# ---------- W1 weather hint ------------------------------------------------------------------------------------------------

def forecast(max_today, max_tomorrow):
    return {"service_response": {"weather.home": {"forecast": [
        {"datetime": "2026-10-22T00:00:00+02:00", "temperature": max_today},
        {"datetime": "2026-10-23T00:00:00+02:00", "temperature": max_tomorrow}]}}}


def test_weather_hint_only_when_hot(conn):
    ha = FakeHA(states={"weather.home": "sunny"})
    ha.responses[("weather", "get_forecasts")] = forecast(20, 32)
    assert "32" in jobs.weather_hint(ha, {}, date(2026, 10, 22))
    ha.responses[("weather", "get_forecasts")] = forecast(20, 24)
    assert jobs.weather_hint(ha, {}, date(2026, 10, 22)) is None
    ha.responses[("weather", "get_forecasts")] = forecast(20, 28)
    assert jobs.weather_hint(ha, {"weather_hot_c": 27}, date(2026, 10, 22)) is not None
    assert jobs.weather_hint(FakeHA(), {}, date(2026, 10, 22)) is None  # no weather entity at all


def test_weather_push_once_per_day_in_the_evening(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    c.close()
    ha = FakeHA(states={"weather.home": "sunny"})
    ha.responses[("weather", "get_forecasts")] = forecast(20, 33)
    state = {}
    opts = {"notify_service": "notify.notify"}
    jobs.run_once(path, ha, datetime(2026, 10, 22, 12, 0), state, opts)
    assert not any("33" in str(d) for _, _, d in ha.service_calls)
    jobs.run_once(path, ha, datetime(2026, 10, 22, 19, 0), state, opts)
    jobs.run_once(path, ha, datetime(2026, 10, 22, 19, 5), state, opts)
    assert sum("33" in str(d) for _, s, d in ha.service_calls if s == "notify") == 1


# ---------- W5 maintenance mode ----------------------------------------------------------------------------------------------

def test_maintenance_buttons_and_state(web):
    t = web.client.get("/cockpit").text
    assert "Wartungsmodus" in t
    assert web.client.post("/cockpit/wartung", data={"aktion": "start"}).status_code == 303
    assert web.ha.service_calls[-1][:2] == ("timer", "start")
    web.client.post("/cockpit/wartung", data={"aktion": "ende"})
    assert web.ha.service_calls[-1][:2] == ("timer", "cancel")
    assert web.client.post("/cockpit/wartung", data={"aktion": "quatsch"}).status_code == 400
    web.ha.states["timer.grow_wartung"] = "active"
    assert "Wartungsmodus aktiv" in web.client.get("/cockpit").text


def test_no_reminders_while_maintenance_is_active(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    mk(c, keim="2026-08-01")
    c.close()
    ha = FakeHA(states={"timer.grow_wartung": "active"})
    jobs.run_once(path, ha, datetime(2026, 10, 22, 10, 0), {}, {"notify_service": "notify.notify"})
    assert ha.service_calls == []


# ---------- W6 quiet hours ----------------------------------------------------------------------------------------------------------

def test_in_quiet_handles_midnight_and_disabled():
    o = {"quiet_from": "22:00", "quiet_to": "07:00"}
    assert jobs.in_quiet(datetime(2026, 10, 22, 23, 0), o) and jobs.in_quiet(datetime(2026, 10, 22, 6, 59), o)
    assert not jobs.in_quiet(datetime(2026, 10, 22, 7, 0), o) and not jobs.in_quiet(datetime(2026, 10, 22, 12, 0), o)
    assert not jobs.in_quiet(datetime(2026, 10, 22, 23, 0), {})
    assert not jobs.in_quiet(datetime(2026, 10, 22, 23, 0), {"quiet_from": "", "quiet_to": ""})


def test_quiet_hours_hold_messages_until_morning_but_not_critical(conn):
    ha, o = FakeHA(), {"quiet_from": "22:00", "quiet_to": "07:00", "notify_service": "notify.notify"}
    night = datetime(2026, 10, 22, 23, 0)
    jobs.notify(ha, o, conn, night, "Titel", "Gießen fällig")
    assert ha.service_calls == []
    jobs.notify(ha, o, conn, night, "Alarm", "Hitze", critical=True)
    assert len(ha.service_calls) == 2
    ha.service_calls.clear()
    jobs.flush_pending(ha, o, conn, datetime(2026, 10, 23, 7, 5))
    assert any("Gießen fällig" in str(d) for _, _, d in ha.service_calls)
    ha.service_calls.clear()
    jobs.flush_pending(ha, o, conn, datetime(2026, 10, 23, 7, 6))
    assert ha.service_calls == []
