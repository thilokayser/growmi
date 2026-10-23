import pytest

from app import entries, plants, watering


def plant(conn, slot=1):
    return plants.add_plant(conn, sorte=f"S{slot}", hersteller="H", keimdatum="2026-09-01", slot=slot,
                            phase="Wachstum", eingesetzt_am="2026-09-01T08:00")


def test_intervention_art_validated(conn):
    p = plant(conn)
    with pytest.raises(ValueError):
        entries.add_intervention(conn, ts="2026-10-20T12:00", plant_id=p, art="Quatsch")
    assert entries.add_intervention(conn, ts="2026-10-20T12:00", plant_id=p, art="Topping")


def test_update_watering_ts_and_liters(conn):
    plant(conn)
    f = watering.add_fertilizer(conn, "Bloom", "BioBizz")
    wid = watering.add_watering(conn, ts="2026-10-20T12:00", liters=2.0, items=[(f, 2.0)])
    entries.update_entry(conn, "watering", wid, ts="2026-10-18T09:00", liters=3.0)
    w = conn.execute("SELECT ts, liters FROM watering WHERE id=?", (wid,)).fetchone()
    assert (w["ts"], w["liters"]) == ("2026-10-18T09:00", 3.0)
    assert conn.execute("SELECT ml_total FROM watering_item WHERE watering_id=?", (wid,)).fetchone()[0] == 6.0


def test_update_rejects_unknown_field_and_bad_liters(conn):
    plant(conn)
    wid = watering.add_watering(conn, ts="2026-10-20T12:00", liters=2.0, items=[])
    with pytest.raises(ValueError):
        entries.update_entry(conn, "watering", wid, id=5)
    with pytest.raises(ValueError):
        entries.update_entry(conn, "watering", wid, liters=0)


def test_delete_watering_removes_children(conn):
    plant(conn)
    f = watering.add_fertilizer(conn, "Bloom", "BioBizz")
    wid = watering.add_watering(conn, ts="2026-10-20T12:00", liters=2.0, items=[(f, 2.0)])
    assert entries.delete_entry(conn, "watering", wid) is None
    for t in ("watering", "watering_plant", "watering_item"):
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0


def test_delete_photo_returns_filename(conn):
    p = plant(conn)
    pid = entries.add_photo(conn, ts="2026-10-20T12:00", plant_id=p, filename="a.jpg")
    assert entries.delete_entry(conn, "photo", pid) == "a.jpg"


def test_list_entries_sorted_newest_first_and_filters_by_plant(conn):
    a, b = plant(conn, 1), plant(conn, 2)
    entries.add_intervention(conn, ts="2026-10-18T09:00", plant_id=a, art="LST", text="gebunden")
    watering.add_watering(conn, ts="2026-10-19T09:00", liters=2.0, items=[], plant_ids=[a, b])
    entries.add_photo(conn, ts="2026-10-20T09:00", plant_id=b, filename="b.jpg")
    all_ = entries.list_entries(conn)
    assert [e["kind"] for e in all_] == ["photo", "watering", "intervention"]
    only_a = entries.list_entries(conn, plant_id=a)
    assert [e["kind"] for e in only_a] == ["watering", "intervention"]
    assert all_[1]["plant_ids"] == [a, b]


def test_set_watering_plants(conn):
    a, b = plant(conn, 1), plant(conn, 2)
    wid = watering.add_watering(conn, ts="2026-10-20T12:00", liters=2.0, items=[], plant_ids=[a])
    entries.set_watering_plants(conn, wid, [a, b])
    assert [r[0] for r in conn.execute("SELECT plant_id FROM watering_plant WHERE watering_id=? ORDER BY 1",
                                       (wid,))] == [a, b]
    with pytest.raises(ValueError):
        entries.set_watering_plants(conn, wid, [])
    assert conn.execute("SELECT COUNT(*) FROM watering_plant WHERE watering_id=?", (wid,)).fetchone()[0] == 2


def test_unknown_plant_rejected_for_intervention_and_photo(conn):
    with pytest.raises(ValueError):
        entries.add_intervention(conn, ts="2026-10-20T12:00", plant_id=99, art="Topping")
    with pytest.raises(ValueError):
        entries.add_photo(conn, ts="2026-10-20T12:00", plant_id=99, filename="x.jpg")
