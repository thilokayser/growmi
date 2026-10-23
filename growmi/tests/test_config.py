import copy

import pytest

from app import config, plants


@pytest.fixture
def fresh(conn):
    config.current = copy.deepcopy(config.EMPTY)
    return conn


def test_fresh_db_is_empty(fresh):
    config.load(fresh)
    assert config.entity("temp") is None
    assert config.slot_count() == 4 and config.devices() == []


def test_save_roundtrip(fresh):
    config.save(fresh, {"temp": "sensor.x"})
    config.current = {}
    config.load(fresh)
    assert config.entity("temp") == "sensor.x"
    assert config.entity("rh") is None


@pytest.mark.parametrize("n", [0, 9])
def test_slots_between_1_and_8(fresh, n):
    with pytest.raises(ValueError):
        config.save(fresh, {"slots": [f"P{i}" for i in range(n)]})


def test_cannot_shrink_below_occupied(fresh):
    plants.add_plant(fresh, sorte="A", hersteller="", keimdatum="2026-10-01", slot=4, phase="Keimling")
    fresh.commit()
    with pytest.raises(ValueError, match="Platz 4"):
        config.save(fresh, {"slots": ["a", "b", "c"]})


def test_state_helper_skips_unset(fresh):
    class Boom:
        def state(self, e):
            raise AssertionError("must not be called")

    assert config.state(Boom(), "temp") is None
    assert config.history(Boom(), "temp", None, None) == []


class StrictHA:
    """Fails on a lookup of an unset entity (None), answers everything else with nothing."""

    def __init__(self):
        self.calls = []

    def _chk(self, e):
        assert e, "ha called with an unset entity"
        self.calls.append(e)

    def state(self, e):
        self._chk(e)

    def history(self, e, *a):
        self._chk(e)
        return []

    def history_points(self, e, *a):
        self._chk(e)
        return []

    def history_states(self, e, *a):
        self._chk(e)
        return []

    def find_entity(self, prefix):
        return None

    def language(self):
        return None

    def call_service(self, *a):
        return True

    def call_service_response(self, *a):
        return None

    def set_state(self, *a, **k):
        return True

    def config_url(self):
        return None

    def ingress_entry(self):
        return "/x"


def test_unset_entities_skip_ha(conn):
    from datetime import date, datetime
    from app import cockpit, events, heatmap, jobs, phase_link

    config.current = copy.deepcopy(config.EMPTY)
    ha, now = StrictHA(), datetime(2026, 10, 22, 12, 0)
    cockpit.build(ha, conn, {}, now)
    events.detect_events(conn, ha, now)
    heatmap.catch_up_hours(conn, ha, now)
    jobs.sync_box_phase(conn, ha, now.strftime("%Y-%m-%dT%H:%M"))
    jobs.climate_summary(conn, ha, date(2026, 10, 21))
    assert phase_link.suggestion(conn, ha, now.date()) is None
    assert ha.calls == []


def test_unset_entities_pages_load(web):
    config.current = copy.deepcopy(config.EMPTY)
    web.client.app.state.ha = StrictHA()
    for path in ("/", "/cockpit", "/verlauf", "/auswertung"):
        assert web.client.get(path).status_code == 200, path
    assert web.client.app.state.ha.calls == []


def test_custom_entity_is_used(web):
    config.save(web.conn(), {**config.EXAMPLE, "temp": "sensor.mein_zelt"})
    web.ha.states.update({"sensor.mein_zelt": "21.5", "sensor.growbox_temperatur": "99"})
    html = web.client.get("/").text
    assert "21.5" in html and "99" not in html


def test_device_list_drives_cockpit_and_wear(web):
    devs = [{"key": "lamp2", "name": "Zusatzlicht", "entity": "switch.z1", "role": "licht", "wear_limit_h": 100.0},
            {"key": "pumpe", "name": "Pumpe", "entity": "switch.p1", "role": "", "wear_limit_h": 50.0}]
    config.save(web.conn(), {**config.EXAMPLE, "devices": devs})
    web.ha.states["switch.z1"] = "on"
    html = web.client.get("/cockpit").text
    assert "Zusatzlicht" in html and "Pumpe" in html
    page = web.client.get("/verschleiss").text
    assert "Zusatzlicht" in page and "Pumpe" in page


def test_no_devices_no_crash(web):
    config.save(web.conn(), {**config.EXAMPLE, "devices": []})
    assert web.client.get("/cockpit").status_code == 200
    assert web.client.get("/verschleiss").status_code == 200
    assert web.client.post("/verschleiss/akf/limit", data={"limit_h": "10"}).status_code == 404


def test_cockpit_hides_unset_sections(web):
    config.save(web.conn(), config.EMPTY)
    html = web.client.get("/cockpit").text
    for text in ("Ventilator-Modus", "Abluft-Modus", "Wartungsmodus", "Batterie"):
        assert text not in html, text


def test_home_hides_unset_climate_tiles(web):
    config.save(web.conn(), config.EMPTY)
    html = web.client.get("/").text
    for text in ("Temperatur", "Luftfeuchte", "VPD", "Box-Phase"):
        assert text not in html, text
    assert web.client.get("/kiosk").status_code == 200


def test_slot_count_six(web):
    config.save(web.conn(), {**config.EXAMPLE, "slots": [f"Ecke {i}" for i in range(1, 7)]})
    c = web.conn()
    plants.add_plant(c, sorte="A", hersteller="", keimdatum="2026-10-01", slot=6, phase="Keimling")
    c.commit()
    with pytest.raises(ValueError, match="1 bis 6"):
        plants.add_plant(c, sorte="B", hersteller="", keimdatum="2026-10-01", slot=7, phase="Keimling")
    html = web.client.get("/").text
    assert 'data-slot="6"' in html and "Ecke 6" in html and 'data-slot="7"' not in html


def test_layout_matches_legacy_for_four(conn):
    from app import routes_home
    cards = {c["slot"]: (c["pos"], c["row"], c["col"]) for c in routes_home.slot_cards(conn)}
    assert cards == {1: ("vorne links", 2, 1), 2: ("vorne rechts", 2, 2), 3: ("hinten links", 1, 1),
                     4: ("hinten rechts", 1, 2)}


def test_layout_for_five_slots(conn):
    from app import routes_home
    config.current = {**config.EXAMPLE, "slots": list("abcde")}
    cards = {c["slot"]: (c["row"], c["col"]) for c in routes_home.slot_cards(conn)}
    assert cards == {1: (3, 1), 2: (3, 2), 3: (2, 1), 4: (2, 2), 5: (1, 1)}


def test_slot_label_skips_default_names():
    config.current = {**config.EXAMPLE, "slots": ["", "Ecke"]}
    assert config.slot_label(1) == "Platz 1" and config.slot_label(2) == "Platz 2 · Ecke"


def test_qr_sheet_uses_names(web):
    config.save(web.conn(), {**config.EXAMPLE, "slots": ["Fenster", "Tür"]})
    html = web.client.get("/qr").text
    assert "Fenster" in html and "Tür" in html and "hinten rechts" not in html


def test_start_on_fresh_install_is_empty(tmp_path):
    import os
    from app.main import create_app
    create_app(str(tmp_path), StrictHA(), run_jobs=False)
    assert config.entity("temp") is None and not os.path.exists(tmp_path / "snapshots")
