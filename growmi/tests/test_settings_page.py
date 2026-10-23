import copy

from app import config, plants


def form(**over):
    base = {**{k: config.EXAMPLE[k] for k in config.ENTITY_KEYS}, "lang": "de", "phase_link": "on", "phase_light_on": "08:00",
            "phase_light_off": "20:00", "slots": "\n".join(config.EXAMPLE["slots"]),
            "dev_key": ["lampe"], "dev_name": ["Licht"], "dev_wear_name": ["Lampe"],
            "dev_entity": ["switch.licht"], "dev_role": ["licht"], "dev_limit": ["25000"]}
    return {**base, **over}


def test_default_slot_names_follow_the_language(web):
    from app import i18n
    config.save(web.conn(), config.EMPTY)
    assert "Platz 1" in web.client.get("/einstellungen").text
    web.client.post("/einstellungen", data=form(lang="en", slots="Spot 1\nSpot 2\nmy corner"))
    assert config.current["slots"] == ["", "", "my corner"]
    assert config.slot_names() == ["Spot 1", "Spot 2", "my corner"]
    i18n.set_lang("de")
    assert config.slot_names()[:2] == ["Platz 1", "Platz 2"]


def test_page_renders_fresh(web):
    config.save(web.conn(), config.EMPTY)
    r = web.client.get("/einstellungen")
    assert r.status_code == 200 and "Einstellungen" in r.text and "Platz 1" in r.text


def test_page_shows_saved_values(web):
    assert "sensor.growbox_temperatur" in web.client.get("/einstellungen").text


def test_save_entities_and_use(web):
    r = web.client.post("/einstellungen", data=form(temp="sensor.zelt_temp", slots="Links\nRechts\nHinten"))
    assert r.status_code == 303
    assert config.entity("temp") == "sensor.zelt_temp" and config.slot_count() == 3
    assert config.devices()[0]["entity"] == "switch.licht"
    assert config.current["phase_light_on"] == "08:00:00"


def test_new_device_gets_a_key(web):
    web.client.post("/einstellungen", data=form(
        dev_key=["lampe", ""], dev_name=["Licht", "Zusatz Pumpe"], dev_wear_name=["Lampe", ""],
        dev_entity=["switch.licht", "switch.pumpe"], dev_role=["licht", ""], dev_limit=["25000", ""]))
    assert [d["key"] for d in config.devices()] == ["lampe", "zusatz-pumpe"]


def test_empty_device_row_is_dropped(web):
    web.client.post("/einstellungen", data=form(
        dev_key=["lampe", ""], dev_name=["Licht", ""], dev_wear_name=["Lampe", ""],
        dev_entity=["switch.licht", ""], dev_role=["licht", ""], dev_limit=["25000", ""]))
    assert len(config.devices()) == 1


def test_invalid_entity_rejected_400(web):
    r = web.client.post("/einstellungen", data=form(temp="kein entity"))
    assert r.status_code == 400 and "keine Entity-ID" in r.text
    assert config.entity("temp") == "sensor.growbox_temperatur"


def test_shrinking_below_occupied_rejected(web):
    c = web.conn()
    plants.add_plant(c, sorte="A", hersteller="", keimdatum="2026-10-01", slot=4, phase="Keimling")
    c.commit()
    r = web.client.post("/einstellungen", data=form(slots="a\nb\nc"))
    assert r.status_code == 400 and "Platz 4" in r.text and config.slot_count() == 4


def test_test_button_reports_state_and_missing(web):
    web.ha.states["sensor.x"] = "21.5"
    assert web.client.get("/einstellungen/test", params={"entity": "sensor.x"}).json() == {"ok": True, "state": "21.5"}
    assert web.client.get("/einstellungen/test", params={"entity": "sensor.nix"}).json()["ok"] is False
    assert web.client.get("/einstellungen/test", params={"entity": "müll"}).status_code == 400


def test_datalist_offers_ha_entities(web):
    web.ha.states["sensor.mein_sensor"] = "1"
    assert "sensor.mein_sensor" in web.client.get("/einstellungen").text


def test_public_twin_404(pub):
    for path in ("/einstellungen", "/einstellungen/test?entity=sensor.x"):
        assert pub.client.get("/s/secret123" + path).status_code == 404
    assert pub.client.post("/s/secret123/einstellungen", data=form()).status_code == 404


def test_public_quick_page_for_slot_above_four(pub):
    config.save(pub.conn(), {**config.EXAMPLE, "slots": [f"P{i}" for i in range(1, 7)]})
    assert pub.client.get("/s/secret123/platz/6").status_code in (200, 307)
    assert pub.client.get("/s/secret123/platz/7").status_code == 404
