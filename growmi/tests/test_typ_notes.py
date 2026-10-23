import pytest

from app import entries, plants, strains
from tests.test_routes_home import count, seed_plant

NEW = {"sorte": "Gorilla Auto", "hersteller": "Barney's", "keimdatum": "2026-10-10", "slot": "3",
       "phase": "Keimling", "eingesetzt_am": "2026-10-12T09:00"}


def rows(web, table):
    c = web.conn()
    r = [dict(x) for x in c.execute(f"SELECT * FROM {table} ORDER BY id")]
    c.close()
    return r


def test_typ_validated_and_stored(conn):
    pid = plants.add_plant(conn, sorte="A", hersteller="", keimdatum="2026-10-01", slot=1, phase="Keimling", typ="auto")
    assert conn.execute("SELECT typ FROM plant WHERE id=?", (pid,)).fetchone()[0] == "auto"
    with pytest.raises(ValueError):
        plants.add_plant(conn, sorte="B", hersteller="", keimdatum="2026-10-01", slot=2, phase="Keimling", typ="x")
    sid = strains.ensure_strain(conn, "Amnesia", "Barney's", typ="photo")
    assert conn.execute("SELECT typ FROM strain WHERE id=?", (sid,)).fetchone()[0] == "photo"
    assert strains.ensure_strain(conn, "amnesia", "barney's", typ="auto") == sid  # existing type stays
    assert conn.execute("SELECT typ FROM strain WHERE id=?", (sid,)).fetchone()[0] == "photo"
    with pytest.raises(ValueError):
        strains.add_strain(conn, "X", typ="x")


def test_planting_saves_typ_on_plant_and_template(web):
    assert web.client.post("/pflanze/neu", data={**NEW, "typ": "auto"}).status_code == 303
    assert rows(web, "plant")[0]["typ"] == "auto" and rows(web, "strain")[0]["typ"] == "auto"
    t = web.client.get("/").text
    assert "Autoflower" in t
    assert web.client.post("/pflanze/neu", data={**NEW, "slot": "4", "typ": "kaputt"}).status_code == 400


def test_template_typ_is_used_when_form_leaves_it_blank(web):
    web.client.post("/stammdaten/sorte", data={"sorte": "Amnesia", "hersteller": "B", "typ": "photo"})
    sid = rows(web, "strain")[0]["id"]
    web.client.post("/pflanze/neu", data={**NEW, "sorte": "", "hersteller": "", "vorlage": str(sid)})
    assert rows(web, "plant")[0]["typ"] == "photo"
    assert 'data-typ="photo"' in web.client.get("/pflanze/neu?slot=2").text


def test_stammdaten_shows_and_edits_typ(web):
    web.client.post("/stammdaten/sorte", data={"sorte": "Gorilla", "typ": "auto"})
    assert "Autoflower" in web.client.get("/stammdaten").text
    sid = rows(web, "strain")[0]["id"]
    web.client.post(f"/stammdaten/sorte/{sid}/bearbeiten", data={"sorte": "Gorilla", "typ": "photo"})
    assert rows(web, "strain")[0]["typ"] == "photo"
    assert "Photoperiodisch" in web.client.get("/stammdaten").text
    assert web.client.post("/stammdaten/sorte", data={"sorte": "Z", "typ": "kaputt"}).status_code == 400


def test_plant_page_shows_and_edits_typ(web):
    pid = seed_plant(web, 1)
    web.client.post(f"/pflanze/{pid}/bearbeiten", data={"sorte": "NL", "typ": "auto"})
    assert "Autoflower" in web.client.get(f"/pflanze/{pid}").text
    assert rows(web, "plant")[0]["typ"] == "auto"


def test_journal_note_on_plant_page(web):
    pid = seed_plant(web, 1)
    t = web.client.get(f"/pflanze/{pid}").text
    assert "Tagebuch" in t and f"/pflanze/{pid}/notiz" in t
    r = web.client.post(f"/pflanze/{pid}/notiz", data={"text": "Blätter leicht gelb, weniger Dünger"})
    assert r.status_code == 303 and r.headers["location"].endswith(f"/pflanze/{pid}")
    row = rows(web, "intervention")[0]
    assert (row["art"], row["plant_id"]) == ("Notiz", pid)
    assert "Blätter leicht gelb" in web.client.get(f"/pflanze/{pid}").text


def test_journal_note_validation(web):
    pid = seed_plant(web, 1)
    assert web.client.post(f"/pflanze/{pid}/notiz", data={"text": "  "}).status_code == 400
    assert count(web, "intervention") == 0
    assert web.client.post("/pflanze/99/notiz", data={"text": "x"}).status_code == 404
    assert "Notiz" in entries.ARTEN
