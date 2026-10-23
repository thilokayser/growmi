from datetime import date, datetime, timedelta

import pytest

from app import db, events, jobs, plants, sensors, tasks, watering
from tests.conftest import FakeHA
from tests.test_routes_home import count, seed_plant

NOW = datetime(2026, 10, 20, 10, 0)
TEMP, ONLINE = "sensor.growbox_temperatur", "binary_sensor.growbox_sensor_online"
MODE = "input_select.grow_ventilator_modus"


def mk(conn, slot=1, keim="2026-09-29", typ=None, phase="Wachstum", since=None):
    return plants.add_plant(conn, sorte=f"S{slot}", hersteller="H", keimdatum=keim, slot=slot, phase=phase,
                            eingesetzt_am=since or f"{keim}T08:00", typ=typ)


# ---------- 2. events from HA -------------------------------------------------------------

def kinds(conn):
    return [r["kind"] for r in events.list_events(conn, 50)][::-1]


def test_heat_and_fan_rule_events_start_and_end_once(conn):
    ha = FakeHA(states={TEMP: "22.0", ONLINE: "on"})
    events.detect_events(conn, ha, NOW)
    for t in ("26.5", "26.9", "29.4", "29.8", "27.5", "23.5"):
        ha.states[TEMP] = t
        events.detect_events(conn, ha, NOW)
    assert kinds(conn) == ["ventilator", "hitze", "hitze_ende", "ventilator"]
    text = [r["text"] for r in events.list_events(conn, 50)][::-1]
    assert "29.4" in text[1] and "26" in text[0]


def test_sensor_online_offline_events_ignore_first_run(conn):
    ha = FakeHA(states={ONLINE: "on"})
    events.detect_events(conn, ha, NOW)
    assert kinds(conn) == []
    ha.states[ONLINE] = "off"
    events.detect_events(conn, ha, NOW)
    ha.states[ONLINE] = "on"
    events.detect_events(conn, ha, NOW)
    assert kinds(conn) == ["sensor", "sensor"]


def test_light_cycle_and_fan_mode_changes_are_logged(conn):
    ha = FakeHA(states={"input_datetime.grow_licht_an": "06:00:00", "input_datetime.grow_licht_aus": "00:00:00",
                        MODE: "Auto"})
    events.detect_events(conn, ha, NOW)
    ha.states.update({"input_datetime.grow_licht_an": "08:00:00", "input_datetime.grow_licht_aus": "20:00:00",
                      MODE: "Dauer an"})
    events.detect_events(conn, ha, NOW)
    texts = [r["text"] for r in events.list_events(conn, 50)]
    assert any("12/12" in t and "08:00" in t for t in texts) and any("Dauer an" in t for t in texts)


def test_events_survive_unavailable_values(conn):
    events.detect_events(conn, FakeHA(states={TEMP: None, ONLINE: None}), NOW)
    assert kinds(conn) == []


# ---------- 4. tasks -----------------------------------------------------------------------

def test_topping_task_due_on_day_21_and_idempotent(conn):
    pid = mk(conn, keim="2026-09-29")
    tasks.generate_tasks(conn, date(2026, 10, 20))
    tasks.generate_tasks(conn, date(2026, 10, 20))
    due = tasks.due_tasks(conn, date(2026, 10, 20))
    assert [t["key"] for t in due] == ["topping"] and due[0]["plant_id"] == pid
    assert tasks.due_tasks(conn, date(2026, 10, 19)) == []


def test_photo_and_auto_rules_differ(conn):
    mk(conn, 1, keim="2026-08-01", typ="photo", phase="Wachstum")
    a = mk(conn, 2, keim="2026-08-01", typ="auto", phase="Wachstum")
    plants.set_phase(conn, 1, "Blüte", "2026-10-01T08:00")
    plants.set_phase(conn, a, "Blüte", "2026-10-01T08:00")
    tasks.generate_tasks(conn, date(2026, 10, 22))  # Blüte day 21 for both
    keys = {(t["plant_id"], t["key"]) for t in conn.execute("SELECT plant_id, key FROM task")}
    assert (1, "entlauben1") in keys and (a, "entlauben1") not in keys
    tasks.generate_tasks(conn, date(2026, 10, 25))  # auto plant is 85 days old
    auto_keys = {r["key"] for r in conn.execute("SELECT key FROM task WHERE plant_id=?", (a,))}
    assert "auto_ernte" in auto_keys and "ernte" not in auto_keys


def test_ancient_tasks_are_not_created_for_backdated_plants(conn):
    mk(conn, keim="2026-06-01")
    tasks.generate_tasks(conn, date(2026, 10, 20))
    assert conn.execute("SELECT COUNT(*) FROM task").fetchone()[0] == 0


def test_done_snooze_and_custom_tasks(conn):
    pid = mk(conn, keim="2026-09-29")
    tasks.generate_tasks(conn, date(2026, 10, 20))
    tid = tasks.due_tasks(conn, date(2026, 10, 20))[0]["id"]
    tasks.snooze(conn, tid, 2, date(2026, 10, 20))
    assert tasks.due_tasks(conn, date(2026, 10, 21)) == [] and len(tasks.due_tasks(conn, date(2026, 10, 22))) == 1
    tasks.mark_done(conn, tid, "2026-10-22T09:00")
    tasks.generate_tasks(conn, date(2026, 10, 30))  # done stays done and is not recreated
    assert "topping" not in [t["key"] for t in tasks.due_tasks(conn, date(2026, 10, 30))]
    assert conn.execute("SELECT COUNT(*) FROM task WHERE key='topping'").fetchone()[0] == 1
    cid = tasks.add_custom(conn, pid, "Töpfe wechseln", date(2026, 10, 25))
    assert tasks.due_tasks(conn, date(2026, 10, 25))[0]["id"] == cid
    with pytest.raises(ValueError):
        tasks.add_custom(conn, pid, "  ", date(2026, 10, 25))


# ---------- 1. sensors for HA ---------------------------------------------------------------

def test_build_sensors_values(conn):
    a = mk(conn, 1, keim="2026-09-29", phase="Wachstum")
    b = mk(conn, 2, keim="2026-10-10", phase="Keimling")
    watering.add_watering(conn, ts="2026-10-17T09:00", liters=2.0, items=[], plant_ids=[a, b])
    s = sensors.build_sensors(conn, NOW, 0.3)
    assert s["sensor.growmi_tage_seit_giessen"][0] == 3
    assert s["sensor.growmi_pflanzen"][0] == 2
    assert s["sensor.growmi_pflanzen"][1]["wachstum"] == 1 and s["sensor.growmi_pflanzen"][1]["keimling"] == 1
    assert s["sensor.growmi_grow_woche"][0] == 4  # oldest plant is 21 days old
    assert s["sensor.growmi_aufgaben"][0] == 0 and s["sensor.growmi_kosten"][0] == 0


def test_build_sensors_without_data_has_no_fake_numbers(conn):
    s = sensors.build_sensors(conn, NOW, 0.0)
    assert s["sensor.growmi_tage_seit_giessen"][0] == "unknown" and s["sensor.growmi_pflanzen"][0] == 0
    assert s["sensor.growmi_grow_woche"][0] == "unknown"


def test_run_once_publishes_sensors_and_logs_events(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    mk(c, keim="2026-09-29")
    c.close()
    ha = FakeHA(states={TEMP: "30.0", ONLINE: "on"})
    jobs.run_once(path, ha, NOW.replace(hour=8), {}, {})
    assert "sensor.growmi_pflanzen" in ha.published
    c = db.connect(path)
    assert "hitze" in [r["kind"] for r in events.list_events(c, 10)]
    assert tasks.due_tasks(c, NOW.date())
    c.close()
    jobs.run_once(path, ha, NOW, {}, {"notify_service": "notify.notify"})
    assert any("Topping" in str(d) for _, _, d in ha.service_calls)  # task shows up in the morning reminder


def test_run_once_isolates_failing_steps(tmp_path, monkeypatch):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    c.close()
    ha = FakeHA()
    monkeypatch.setattr(events, "detect_events", lambda *a: 1 / 0)
    jobs.run_once(path, ha, NOW, {}, {})
    assert "sensor.growmi_pflanzen" in ha.published


# ---------- 3. cockpit -----------------------------------------------------------------------

def live(web):
    web.ha.states.update({"switch.grow_light": "on",
                          "switch.grow_exhaust": "off",
                          "switch.grow_fan": "on", MODE: "Auto",
                          ONLINE: "on", "sensor.growbox_batterie": "100", TEMP: "22.5"})
    web.ha.histories.update({TEMP: [21.0, 22.0, 23.0], "sensor.growbox_vpd": [0.8, 0.9, 1.0]})


def test_cockpit_shows_devices_charts_and_clean_status(web):
    live(web)
    r = web.client.get("/cockpit")
    t = r.text
    assert r.status_code == 200 and "<h1" in t
    for needle in ("Licht", "Abluft", "Ventilator", "Batterie", "100 %", "<polyline"):
        assert needle in t
    assert "Keine Alarme" in t


def test_cockpit_alerts(web):
    live(web)
    web.ha.states.update({ONLINE: "off", "sensor.growbox_batterie": "12", TEMP: "30.1", MODE: "Dauer an"})
    t = web.client.get("/cockpit").text
    for needle in ("Klimasensor offline", "Batterie schwach", "Hitze", "Dauer an"):
        assert needle in t


def test_cockpit_works_when_ha_is_silent(web):
    r = web.client.get("/cockpit")
    assert r.status_code == 200 and "–" in r.text


def test_cockpit_ventilator_mode_button(web):
    live(web)
    r = web.client.post("/cockpit/ventilator", data={"modus": "Dauer aus"})
    assert r.status_code == 303
    assert web.ha.service_calls[-1] == ("input_select", "select_option",
                                        {"entity_id": MODE, "option": "Dauer aus"})
    assert web.client.post("/cockpit/ventilator", data={"modus": "Quatsch"}).status_code == 400


def test_cockpit_lists_due_tasks_and_buttons_work(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    tid = tasks.add_custom(c, pid, "Töpfe wechseln", date.today())
    c.close()
    t = web.client.get("/cockpit").text
    assert "Töpfe wechseln" in t and f"/aufgabe/{tid}/erledigt" in t
    assert web.client.post(f"/aufgabe/{tid}/spaeter", data={"back": "/cockpit"}).status_code == 303
    assert "Töpfe wechseln" not in web.client.get("/cockpit").text
    assert web.client.post(f"/aufgabe/{tid}/erledigt").status_code == 303
    assert web.client.post("/aufgabe/99/erledigt").status_code == 404


def test_plant_page_task_form_events_and_verlauf_events(web):
    pid = seed_plant(web, 1)
    r = web.client.post(f"/pflanze/{pid}/aufgabe", data={"title": "Netz spannen", "due": "2026-11-01"})
    assert r.status_code == 303
    c = web.conn()
    events.add_event(c, "2026-10-20T10:00", "hitze", "Hitze: 29.4 °C (Schwelle 29 °C)")
    c.close()
    t = web.client.get(f"/pflanze/{pid}").text
    assert "Netz spannen" in t and "Hitze: 29.4" in t
    assert "Hitze: 29.4" in web.client.get("/verlauf").text
    assert web.client.post(f"/pflanze/{pid}/aufgabe", data={"title": " ", "due": "2026-11-01"}).status_code == 400
    assert web.client.post(f"/pflanze/{pid}/aufgabe", data={"title": "x", "due": "morgen"}).status_code == 400


def test_nav_has_cockpit_tab(web):
    t = web.client.get("/").text
    assert 'href="/cockpit"' in t


def test_autoflower_is_recognised_by_name_and_wrong_open_tasks_are_removed(conn):
    pid = plants.add_plant(conn, sorte="Permanent Jealousy XL Auto", hersteller="H", keimdatum="2026-09-01", slot=1,
                           phase="Wachstum", eingesetzt_am="2026-09-01T08:00")  # typ not set yet
    conn.execute("INSERT INTO task(plant_id, key, title, due) VALUES (?, 'umstellen', 'x', '2026-10-01')", (pid,))
    conn.execute("INSERT INTO task(plant_id, key, title, due) VALUES (?, 'custom-1', 'Eigene', '2026-10-01')", (pid,))
    tasks.generate_tasks(conn, date(2026, 10, 6))  # day 35 after germination
    keys = {r["key"] for r in conn.execute("SELECT key FROM task WHERE plant_id=?", (pid,))}
    assert "umstellen" not in keys and "custom-1" in keys and "auto_bluete" in keys


def test_explicit_type_beats_the_name(conn):
    pid = plants.add_plant(conn, sorte="Auto Fake", hersteller="", keimdatum="2026-09-01", slot=1, phase="Wachstum",
                           eingesetzt_am="2026-09-01T08:00", typ="photo")
    assert not tasks.is_auto(conn.execute("SELECT * FROM plant WHERE id=?", (pid,)).fetchone())


def test_cockpit_exhaust_mode_button_and_event(web, conn):
    web.ha.states["input_select.grow_abluft_modus"] = "Feuchteschutz"
    t = web.client.get("/cockpit").text
    assert "Abluft-Modus" in t and "Feuchteschutz" in t and "Standard" in t
    assert web.client.post("/cockpit/abluft", data={"modus": "Standard"}).status_code == 303
    assert web.ha.service_calls[-1] == ("input_select", "select_option",
                                        {"entity_id": "input_select.grow_abluft_modus", "option": "Standard"})
    assert web.client.post("/cockpit/abluft", data={"modus": "Quatsch"}).status_code == 400
    ha = FakeHA(states={"input_select.grow_abluft_modus": "Feuchteschutz"})
    events.detect_events(conn, ha, NOW)
    ha.states["input_select.grow_abluft_modus"] = "Standard"
    events.detect_events(conn, ha, NOW)
    assert any("Abluft-Modus: Standard" in r["text"] for r in events.list_events(conn, 5))
