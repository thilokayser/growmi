from app import db

TABLES = {
    "plant", "plant_phase", "fertilizer", "recipe_item", "watering",
    "watering_plant", "watering_item", "intervention", "photo",
    "box_phase_change", "climate_day",
}


def test_schema_has_all_tables(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_foreign_keys_on(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
