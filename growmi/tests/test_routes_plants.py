from app import entries, plants, watering
from tests.test_routes_home import count, seed_plant

NEW = {"sorte": "Blue Dream", "hersteller": "Barney's", "keimdatum": "2026-10-10", "slot": "3",
       "phase": "Keimling", "topf": "3 L", "notiz": "", "eingesetzt_am": "2026-10-12T09:00"}


def test_new_plant_on_taken_slot_shows_error(web):
    seed_plant(web, 3)
    r = web.client.post("/pflanze/neu", data=NEW)
    assert r.status_code == 400 and "belegt" in r.text
    assert count(web, "plant") == 1


def test_new_plant_form_prefills_slot(web):
    assert 'value="2" selected' in web.client.get("/pflanze/neu?slot=2").text


def test_new_plant_creates_card_on_home(web):
    r = web.client.post("/pflanze/neu", data=NEW)
    assert r.status_code == 303
    assert "Blue Dream" in web.client.get("/").text


def test_plant_detail_lists_phases_and_entries(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    plants.set_phase(c, pid, "Blüte", "2026-10-15T08:00")
    entries.add_intervention(c, ts="2026-10-16T09:00", plant_id=pid, art="Topping", text="oben")
    watering.add_watering(c, ts="2026-10-17T09:00", liters=2.0, items=[], plant_ids=[pid])
    c.close()
    t = web.client.get(f"/pflanze/{pid}").text
    for needle in ("Northern Lights", "Wachstum", "Blüte", "Topping", "2 L", "Wasser gesamt"):
        assert needle in t


def test_unknown_plant_404(web):
    assert web.client.get("/pflanze/99").status_code == 404


def test_change_phase_adds_history_row(web):
    pid = seed_plant(web, 1)
    r = web.client.post(f"/pflanze/{pid}/phase", data={"phase": "Blüte", "ab": "2026-10-15T08:00"})
    assert r.status_code == 303
    c = web.conn()
    assert plants.current_phase(c, pid) == "Blüte"
    c.close()


def test_finish_plant_with_comma_weight(web):
    pid = seed_plant(web, 1)
    r = web.client.post(f"/pflanze/{pid}/ausziehen", data={"ts": "2026-12-01T10:00", "trocken_g": "31,5",
                                                          "nass_g": ""})
    assert r.status_code == 303
    c = web.conn()
    row = c.execute("SELECT trocken_g, nass_g FROM plant WHERE id=?", (pid,)).fetchone()
    assert (row["trocken_g"], row["nass_g"]) == (31.5, None)
    assert plants.slot_occupant(c, 1) is None
    c.close()


def test_finish_plant_bad_weight_shows_error(web):
    pid = seed_plant(web, 1)
    r = web.client.post(f"/pflanze/{pid}/ausziehen", data={"ts": "2026-12-01T10:00", "trocken_g": "viel"})
    assert r.status_code == 400
    c = web.conn()
    assert plants.slot_occupant(c, 1) == pid
    c.close()


def test_edit_plant_data(web):
    pid = seed_plant(web, 1)
    web.client.post(f"/pflanze/{pid}/bearbeiten", data={"sorte": "NL #5", "hersteller": "X",
                                                        "keimdatum": "2026-09-02", "topf": "", "notiz": "n"})
    assert "NL #5" in web.client.get(f"/pflanze/{pid}").text


def test_backdated_entry_editable(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    wid = watering.add_watering(c, ts="2026-10-20T12:00", liters=2.0, items=[], plant_ids=[pid])
    c.close()
    assert "2026-10-20T12:00" in web.client.get(f"/eintrag/watering/{wid}").text
    r = web.client.post(f"/eintrag/watering/{wid}/bearbeiten",
                        data={"ts": "2026-10-05T08:30", f"liters_{pid}": "3,5", "ph": "", "ec": ""})
    assert r.status_code == 303
    c = web.conn()
    row = c.execute("SELECT ts, liters FROM watering WHERE id=?", (wid,)).fetchone()
    c.close()
    assert (row["ts"], row["liters"]) == ("2026-10-05T08:30", 3.5)


def test_delete_entry_and_confirm_attribute(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    wid = watering.add_watering(c, ts="2026-10-20T12:00", liters=2.0, items=[], plant_ids=[pid])
    c.close()
    assert "confirm(" in web.client.get(f"/pflanze/{pid}").text
    assert web.client.post(f"/eintrag/watering/{wid}/loeschen").status_code == 303
    assert count(web, "watering") == 0


def test_stammdaten_recipe_roundtrip(web):
    web.client.post("/stammdaten/duenger", data={"produkt": "Bloom", "hersteller": "BioBizz"})
    c = web.conn()
    fid = c.execute("SELECT id FROM fertilizer").fetchone()[0]
    c.close()
    r = web.client.post("/stammdaten/rezept/Blüte", data={f"ml_{fid}": "2,5"})
    assert r.status_code == 303
    page = web.client.get("/stammdaten").text
    assert "Bloom" in page and 'value="2.5"' in page
    c = web.conn()
    assert [(i.produkt, i.ml_per_l) for i in watering.get_recipe(c, "Blüte")] == [("Bloom", 2.5)]
    c.close()


def test_stammdaten_delete_fertilizer(web):
    web.client.post("/stammdaten/duenger", data={"produkt": "Bloom", "hersteller": "BioBizz"})
    c = web.conn()
    fid = c.execute("SELECT id FROM fertilizer").fetchone()[0]
    c.close()
    assert web.client.post(f"/stammdaten/duenger/{fid}/loeschen").status_code == 303
    assert count(web, "fertilizer") == 0


def finished_plant(web, **kw):
    pid = seed_plant(web, 1)
    c = web.conn()
    plants.finish_plant(c, pid, "2026-12-01T10:00", **kw)
    c.close()
    return pid


def weights(web, pid):
    c = web.conn()
    row = c.execute("SELECT trocken_g, nass_g FROM plant WHERE id=?", (pid,)).fetchone()
    c.close()
    return (row["trocken_g"], row["nass_g"])


def test_set_weights_after_finish(web):
    pid = finished_plant(web)
    assert f"/pflanze/{pid}/gewicht" in web.client.get(f"/pflanze/{pid}").text
    r = web.client.post(f"/pflanze/{pid}/gewicht", data={"trocken_g": "31,5", "nass_g": "120"})
    assert r.status_code == 303 and weights(web, pid) == (31.5, 120.0)


def test_set_weights_bad_input_rejected_and_blank_clears(web):
    pid = finished_plant(web, trocken_g=10.0)
    assert web.client.post(f"/pflanze/{pid}/gewicht", data={"trocken_g": "viel"}).status_code == 400
    assert weights(web, pid) == (10.0, None)
    web.client.post(f"/pflanze/{pid}/gewicht", data={"trocken_g": "", "nass_g": ""})
    assert weights(web, pid) == (None, None)


def test_delete_plant_route(web):
    pid = seed_plant(web, 1)
    assert "/loeschen" in web.client.get(f"/pflanze/{pid}").text
    assert web.client.post(f"/pflanze/{pid}/loeschen").status_code == 303
    assert count(web, "plant") == 0
    assert web.client.post("/pflanze/99/loeschen").status_code == 404


def test_edit_plant_slot_and_eingesetzt(web):
    pid = seed_plant(web, 1)
    base = {"sorte": "NL", "hersteller": "X", "keimdatum": "2026-09-01", "topf": "", "notiz": ""}
    r = web.client.post(f"/pflanze/{pid}/bearbeiten", data={**base, "slot": "3",
                                                           "eingesetzt_am": "2026-08-30T10:00"})
    assert r.status_code == 303
    c = web.conn()
    row = c.execute("SELECT slot, eingesetzt_am FROM plant WHERE id=?", (pid,)).fetchone()
    c.close()
    assert (row["slot"], row["eingesetzt_am"]) == (3, "2026-08-30T10:00")


def test_edit_plant_slot_taken_shows_error(web):
    pid = seed_plant(web, 1)
    seed_plant(web, 2)
    r = web.client.post(f"/pflanze/{pid}/bearbeiten", data={"sorte": "NL", "slot": "2"})
    assert r.status_code == 400 and "belegt" in r.text


def test_delete_phase_route(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    plants.set_phase(c, pid, "Blüte", "2026-10-15T08:00")
    blute = c.execute("SELECT id FROM plant_phase WHERE phase='Blüte'").fetchone()[0]
    first = c.execute("SELECT id FROM plant_phase WHERE phase='Wachstum'").fetchone()[0]
    c.close()
    assert web.client.post(f"/pflanze/{pid}/phase/{blute}/loeschen").status_code == 303
    assert web.client.post(f"/pflanze/{pid}/phase/{first}/loeschen").status_code == 400
    c = web.conn()
    assert plants.current_phase(c, pid) == "Wachstum"
    c.close()


def test_phase_form_rejects_geerntet(web):
    pid = seed_plant(web, 1)
    r = web.client.post(f"/pflanze/{pid}/phase", data={"phase": "Geerntet", "ab": "2026-10-15T08:00"})
    assert r.status_code == 400 and "Ausziehen" in r.text
    c = web.conn()
    assert plants.current_phase(c, pid) == "Wachstum"
    c.close()
    assert '<option>Geerntet</option>' not in web.client.get(f"/pflanze/{pid}").text


def test_watering_edit_plants(web):
    a, b = seed_plant(web, 1), seed_plant(web, 2)
    c = web.conn()
    wid = watering.add_watering(c, ts="2026-10-20T12:00", liters=2.0, items=[], plant_ids=[a])
    c.close()
    form = web.client.get(f"/eintrag/watering/{wid}").text
    assert f'name="liters_{b}"' in form
    data = {"ts": "2026-10-20T12:00"}
    assert web.client.post(f"/eintrag/watering/{wid}/bearbeiten",
                           data={**data, f"liters_{a}": "1", f"liters_{b}": "3"}).status_code == 303
    c = web.conn()
    rows = c.execute("SELECT plant_id, liters FROM watering_plant WHERE watering_id=? ORDER BY 1", (wid,)).fetchall()
    c.close()
    assert [tuple(r) for r in rows] == [(a, 1.0), (b, 3.0)]
    assert web.client.post(f"/eintrag/watering/{wid}/bearbeiten", data=data).status_code == 400


def test_recipe_save_with_deleted_fertilizer_shows_error(web):
    r = web.client.post("/stammdaten/rezept/Blüte", data={"ml_99": "2"})
    assert r.status_code == 400


def kreis_of(web, pid):
    c = web.conn()
    v = c.execute("SELECT kreis FROM plant WHERE id=?", (pid,)).fetchone()[0]
    c.close()
    return v


def test_new_plant_with_circle_colour(web):
    assert 'name="kreis" value="" checked' in web.client.get("/pflanze/neu").text
    assert web.client.post("/pflanze/neu", data={**NEW, "kreis": "#F2A37C"}).status_code == 303
    pid = plants.slot_occupant(web.conn(), 3)
    assert kreis_of(web, pid) == "#f2a37c"
    assert "--ph:#f2a37c" in web.client.get("/").text


def test_own_colour_and_bad_values(web):
    assert web.client.post("/pflanze/neu", data={**NEW, "kreis": "eigene", "kreis_farbe": "#123456"}).status_code == 303
    pid = plants.slot_occupant(web.conn(), 3)
    assert kreis_of(web, pid) == "#123456"
    page = web.client.get(f"/pflanze/{pid}").text
    assert 'value="eigene" checked' in page and 'value="#123456"' in page
    r = web.client.post(f"/pflanze/{pid}/bearbeiten", data={"sorte": "Blue Dream", "kreis": "url(x)"})
    assert r.status_code == 400 and kreis_of(web, pid) == "#123456"


def test_circle_shows_latest_photo_or_falls_back(web):
    pid = seed_plant(web, 1, "Alpha")
    assert web.client.post(f"/pflanze/{pid}/bearbeiten", data={"sorte": "Alpha", "kreis": "foto"}).status_code == 303
    assert kreis_of(web, pid) == "foto"
    home = web.client.get("/").text
    assert 'class="canopy photo' not in home and "canopy ph-" in home  # no photo yet: phase colour
    c = web.conn()
    c.execute("INSERT INTO photo(ts, plant_id, filename) VALUES ('2026-10-01T10:00', ?, 'alt.jpg')", (pid,))
    c.execute("INSERT INTO photo(ts, plant_id, filename) VALUES ('2026-10-05T10:00', ?, 'neu.jpg')", (pid,))
    c.commit()
    c.close()
    home = web.client.get("/").text
    assert 'class="canopy photo' in home and "/fotos/t_neu.jpg" in home and "t_alt.jpg" not in home
    assert web.client.post(f"/pflanze/{pid}/bearbeiten", data={"sorte": "Alpha", "kreis": ""}).status_code == 303
    assert kreis_of(web, pid) is None and "t_neu.jpg" not in web.client.get("/").text
