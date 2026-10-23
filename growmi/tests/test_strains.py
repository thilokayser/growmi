import sqlite3

import pytest

from app import db, plants, strains
from tests.test_routes_home import count, seed_plant

NEW = {"sorte": "Blue Dream", "hersteller": "Barney's", "keimdatum": "2026-10-10", "slot": "3",
       "phase": "Keimling", "eingesetzt_am": "2026-10-12T09:00"}


def test_ensure_strain_is_get_or_create_case_insensitive(conn):
    a = strains.ensure_strain(conn, "Northern Lights", "Sensi Seeds")
    assert strains.ensure_strain(conn, "northern lights", "SENSI seeds") == a
    assert strains.ensure_strain(conn, "Northern Lights", "") != a
    with pytest.raises(ValueError):
        strains.ensure_strain(conn, "  ", "x")


def test_add_update_duplicate_rejected(conn):
    a = strains.add_strain(conn, "Amnesia Haze", "Barney's", notiz="Sativa")
    with pytest.raises(ValueError):
        strains.add_strain(conn, "amnesia haze", "barney's")
    b = strains.add_strain(conn, "Blue Dream", "Barney's")
    with pytest.raises(ValueError):
        strains.update_strain(conn, b, sorte="Amnesia Haze")
    strains.update_strain(conn, a, notiz="Sativa, lang")
    assert conn.execute("SELECT notiz FROM strain WHERE id=?", (a,)).fetchone()[0] == "Sativa, lang"


def test_list_counts_plants_and_delete_keeps_them(conn):
    sid = strains.ensure_strain(conn, "Northern Lights", "Sensi")
    for slot in (1, 2):
        plants.add_plant(conn, sorte="northern lights", hersteller="Sensi", keimdatum="2026-09-01", slot=slot,
                         phase="Keimling", eingesetzt_am="2026-09-01T08:00")
    row = strains.list_strains(conn)[0]
    assert (row["sorte"], row["plant_count"]) == ("Northern Lights", 2)
    strains.delete_strain(conn, sid)
    assert strains.list_strains(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM plant").fetchone()[0] == 2


def test_migration_creates_strain_table_backfilled_once(tmp_path):
    path = str(tmp_path / "old.db")
    c = db.connect(path)
    db.init_schema(c)
    c.execute("DROP TABLE strain")
    c.execute("INSERT INTO plant(sorte, hersteller, slot, eingesetzt_am) VALUES ('A','H',1,'2026-10-01T08:00')")
    c.execute("INSERT INTO plant(sorte, hersteller, slot, eingesetzt_am) VALUES ('a','h',2,'2026-10-01T08:00')")
    c.commit()
    db.init_schema(c)
    assert [(r["sorte"], r["hersteller"]) for r in strains.list_strains(c)] == [("A", "H")]
    c.execute("DELETE FROM strain")
    c.commit()
    db.init_schema(c)  # restart must not resurrect a deleted template
    assert strains.list_strains(c) == []
    c.close()


def strain_rows(web):
    c = web.conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM strain ORDER BY id")]
    c.close()
    return rows


def test_planting_saves_strain_once(web):
    assert web.client.post("/pflanze/neu", data=NEW).status_code == 303
    web.client.post("/pflanze/neu", data={**NEW, "slot": "4", "sorte": "blue dream"})
    rows = strain_rows(web)
    assert [(r["sorte"], r["hersteller"]) for r in rows] == [("Blue Dream", "Barney's")]


def test_planting_form_offers_templates(web):
    web.client.post("/stammdaten/sorte", data={"sorte": "Amnesia Haze", "hersteller": "Barney's"})
    t = web.client.get("/pflanze/neu?slot=2").text
    assert 'data-sorte="Amnesia Haze"' in t and 'data-hersteller="Barney&#39;s"' in t
    assert 'name="vorlage"' in t


def test_planting_with_template_and_blank_sorte_uses_template(web):
    web.client.post("/stammdaten/sorte", data={"sorte": "Amnesia Haze", "hersteller": "Barney's"})
    sid = strain_rows(web)[0]["id"]
    r = web.client.post("/pflanze/neu", data={**NEW, "sorte": "", "hersteller": "", "vorlage": str(sid)})
    assert r.status_code == 303
    c = web.conn()
    p = c.execute("SELECT sorte, hersteller FROM plant").fetchone()
    c.close()
    assert (p["sorte"], p["hersteller"]) == ("Amnesia Haze", "Barney's")
    assert len(strain_rows(web)) == 1


def test_typed_values_win_over_template(web):
    web.client.post("/stammdaten/sorte", data={"sorte": "Amnesia Haze", "hersteller": "Barney's"})
    sid = strain_rows(web)[0]["id"]
    web.client.post("/pflanze/neu", data={**NEW, "vorlage": str(sid)})
    assert [r["sorte"] for r in strain_rows(web)] == ["Amnesia Haze", "Blue Dream"]


def test_blank_sorte_without_template_shows_error(web):
    r = web.client.post("/pflanze/neu", data={**NEW, "sorte": ""})
    assert r.status_code == 400 and count(web, "plant") == 0


def test_editing_plant_saves_strain(web):
    pid = seed_plant(web, 1)
    web.client.post(f"/pflanze/{pid}/bearbeiten", data={"sorte": "Neue Sorte", "hersteller": "Neu GmbH"})
    assert ("Neue Sorte", "Neu GmbH") in [(r["sorte"], r["hersteller"]) for r in strain_rows(web)]


def test_stammdaten_lists_strains_with_plant_count(web):
    web.client.post("/pflanze/neu", data=NEW)
    t = web.client.get("/stammdaten").text
    assert "Blue Dream" in t and "Barney" in t and "1 Pflanze" in t
    assert 'aria-label="Sorte bearbeiten"' in t and 'aria-label="Sorte löschen"' in t


def test_strain_crud_routes(web):
    assert web.client.post("/stammdaten/sorte", data={"sorte": "X", "hersteller": "Y", "notiz": "n"}).status_code == 303
    sid = strain_rows(web)[0]["id"]
    assert web.client.post("/stammdaten/sorte", data={"sorte": "x", "hersteller": "y"}).status_code == 400
    assert web.client.post("/stammdaten/sorte", data={"sorte": ""}).status_code == 400
    assert 'value="X"' in web.client.get(f"/stammdaten/sorte/{sid}").text
    r = web.client.post(f"/stammdaten/sorte/{sid}/bearbeiten", data={"sorte": "X2", "hersteller": "Y", "notiz": ""})
    assert r.status_code == 303 and strain_rows(web)[0]["sorte"] == "X2"
    assert web.client.post(f"/stammdaten/sorte/{sid}/loeschen").status_code == 303
    assert strain_rows(web) == []
    assert web.client.get("/stammdaten/sorte/99").status_code == 404
    assert web.client.post("/stammdaten/sorte/99/bearbeiten", data={"sorte": "x"}).status_code == 404


def test_editing_template_does_not_rename_existing_plants(web):
    web.client.post("/pflanze/neu", data=NEW)
    sid = strain_rows(web)[0]["id"]
    web.client.post(f"/stammdaten/sorte/{sid}/bearbeiten", data={"sorte": "Umbenannt", "hersteller": "Barney's"})
    c = web.conn()
    assert c.execute("SELECT sorte FROM plant").fetchone()[0] == "Blue Dream"
    c.close()
