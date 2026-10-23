from datetime import date, datetime

from app import events, jobs, phase_link, plants
from tests.conftest import FakeHA
from tests.test_routes_home import seed_plant

BOX = "input_select.grow_phase"
TODAY = date(2026, 10, 22)


def mk(conn, slot, phase, typ="photo"):
    return plants.add_plant(conn, sorte=f"S{slot}", hersteller="", keimdatum="2026-09-01", slot=slot, phase=phase,
                            eingesetzt_am="2026-09-01T08:00", typ=typ)


def test_suggests_highest_phase_of_photo_plants_ahead_of_the_box(conn):
    mk(conn, 1, "Wachstum")
    mk(conn, 2, "Blüte")
    s = phase_link.suggestion(conn, FakeHA(states={BOX: "Wachstum"}), TODAY)
    assert (s["target"], s["box"], s["names"]) == ("Blüte", "Wachstum", ["S2"]) and s["auto_present"] is False


def test_no_suggestion_when_box_is_current_or_unknown_or_only_autos_are_ahead(conn):
    mk(conn, 1, "Blüte", typ="auto")
    assert phase_link.suggestion(conn, FakeHA(states={BOX: "Wachstum"}), TODAY) is None
    mk(conn, 2, "Blüte")
    assert phase_link.suggestion(conn, FakeHA(states={BOX: "Blüte"}), TODAY) is None
    assert phase_link.suggestion(conn, FakeHA(states={BOX: None}), TODAY) is None
    assert phase_link.suggestion(conn, FakeHA(states={BOX: "Quatsch"}), TODAY) is None


def test_auto_plants_are_flagged_in_the_suggestion(conn):
    mk(conn, 1, "Blüte")
    mk(conn, 2, "Wachstum", typ="auto")
    assert phase_link.suggestion(conn, FakeHA(states={BOX: "Wachstum"}), TODAY)["auto_present"] is True


def test_snooze_hides_for_today_only(conn):
    mk(conn, 1, "Blüte")
    ha = FakeHA(states={BOX: "Wachstum"})
    phase_link.snooze(conn, TODAY)
    assert phase_link.suggestion(conn, ha, TODAY) is None
    assert phase_link.suggestion(conn, ha, date(2026, 10, 23)) is not None


def test_apply_sets_phase_light_and_logs_event(conn):
    ha = FakeHA()
    assert phase_link.apply(ha, conn, "Blüte", with_light=True, now=datetime(2026, 10, 22, 9, 0)) is True
    assert ha.service_calls == [("input_select", "select_option", {"entity_id": BOX, "option": "Blüte"}),
                                ("script", "grow_licht_preset", {"an": "08:00:00", "aus": "20:00:00"})]
    assert "12/12" in events.list_events(conn, 5)[0]["text"]
    ha2 = FakeHA()
    phase_link.apply(ha2, conn, "Wachstum", with_light=True, now=datetime(2026, 10, 22, 9, 0))
    assert len(ha2.service_calls) == 1  # light preset only belongs to Blüte


def test_apply_reports_failure_and_logs_nothing(conn):
    ha = FakeHA()
    ha.fail = True
    assert phase_link.apply(ha, conn, "Blüte", with_light=False, now=datetime(2026, 10, 22, 9, 0)) is False
    assert events.list_events(conn, 5) == []


def test_banner_on_home_and_plant_page_and_buttons(web):
    web.ha.states[BOX] = "Wachstum"
    pid = seed_plant(web, 1)
    web.client.post(f"/pflanze/{pid}", data={})  # no such route, ignored
    r = web.client.post(f"/pflanze/{pid}/phase", data={"phase": "Blüte", "ab": "2026-10-22T08:00"})
    assert r.status_code == 303
    for url in ("/", "/cockpit", f"/pflanze/{pid}"):
        t = web.client.get(url).text
        assert "Box auf Blüte" in t and 'action="/box/phase"' in t and "12/12" in t, url
    r = web.client.post("/box/phase", data={"phase": "Blüte", "licht": "1", "back": "/cockpit"})
    assert r.status_code == 303 and r.headers["location"] == "/cockpit"
    assert [c[1] for c in web.ha.service_calls] == ["select_option", "grow_licht_preset"]
    web.ha.states[BOX] = "Wachstum"
    assert web.client.post("/box/spaeter", data={"back": "/"}).status_code == 303
    assert "Box auf Blüte" not in web.client.get("/").text


def test_box_phase_route_rejects_bad_input_and_ha_failure(web):
    assert web.client.post("/box/phase", data={"phase": "Quatsch"}).status_code == 400
    web.ha.fail = True
    assert web.client.post("/box/phase", data={"phase": "Blüte"}).status_code == 502


def test_daily_reminder_mentions_the_phase_suggestion(tmp_path):
    from app import db
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    mk(c, 1, "Blüte")
    c.close()
    ha = FakeHA(states={BOX: "Wachstum"})
    jobs.run_once(path, ha, datetime(2026, 10, 22, 10, 0), {}, {"notify_service": "notify.notify"})
    assert any("Box-Phase" in str(d) for _, _, d in ha.service_calls)
