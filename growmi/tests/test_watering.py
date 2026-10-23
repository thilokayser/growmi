import pytest

from app import plants, watering


def plant(conn, slot, **kw):
    return plants.add_plant(conn, sorte=f"S{slot}", hersteller="H", keimdatum="2026-09-01", slot=slot,
                            phase="Wachstum", eingesetzt_am=kw.pop("eingesetzt_am", "2026-09-01T08:00"), **kw)


def fert(conn, name="Bloom"):
    return watering.add_fertilizer(conn, name, "BioBizz")


def test_add_watering_snapshot(conn):
    plant(conn, 1)
    f = fert(conn)
    wid = watering.add_watering(conn, ts="2026-10-20T12:00", liters=3.0, items=[(f, 2.0)])
    row = conn.execute("SELECT produkt, hersteller, ml_per_l, ml_total FROM watering_item WHERE watering_id=?",
                       (wid,)).fetchone()
    assert tuple(row) == ("Bloom", "BioBizz", 2.0, 6.0)


def test_watering_defaults_to_all_occupied(conn):
    a, b = plant(conn, 1), plant(conn, 2)
    c = plant(conn, 3)
    plants.finish_plant(conn, c, "2026-10-10T08:00")
    wid = watering.add_watering(conn, ts="2026-10-20T12:00", liters=3.0, items=[])
    ids = [r[0] for r in conn.execute("SELECT plant_id FROM watering_plant WHERE watering_id=? ORDER BY 1", (wid,))]
    assert ids == [a, b]


def test_watering_water_only(conn):
    plant(conn, 1)
    wid = watering.add_watering(conn, ts="2026-10-20T12:00", liters=1.5, items=[], ph=6.1, ec=1.2)
    assert conn.execute("SELECT COUNT(*) FROM watering_item WHERE watering_id=?", (wid,)).fetchone()[0] == 0
    row = conn.execute("SELECT ph, ec FROM watering WHERE id=?", (wid,)).fetchone()
    assert (row["ph"], row["ec"]) == (6.1, 1.2)


def test_watering_no_plants_raises(conn):
    with pytest.raises(ValueError):
        watering.add_watering(conn, ts="2026-10-20T12:00", liters=2.0, items=[])
    a = plant(conn, 1)
    with pytest.raises(ValueError):
        watering.add_watering(conn, ts="2026-10-20T12:00", liters=2.0, items=[], plant_ids=[])
    assert conn.execute("SELECT COUNT(*) FROM watering").fetchone()[0] == 0
    assert a


@pytest.mark.parametrize("liters", [0, -1])
def test_watering_bad_liters_raises(conn, liters):
    plant(conn, 1)
    with pytest.raises(ValueError):
        watering.add_watering(conn, ts="2026-10-20T12:00", liters=liters, items=[])


def test_recipe_change_does_not_touch_old_watering(conn):
    plant(conn, 1)
    f = fert(conn)
    watering.set_recipe(conn, "Blüte", [(f, 2.0)])
    items = [(r.fertilizer_id, r.ml_per_l) for r in watering.get_recipe(conn, "Blüte")]
    wid = watering.add_watering(conn, ts="2026-10-20T12:00", liters=3.0, items=items)
    watering.set_recipe(conn, "Blüte", [(f, 9.0)])
    watering.delete_fertilizer(conn, f)
    row = conn.execute("SELECT produkt, ml_total FROM watering_item WHERE watering_id=?", (wid,)).fetchone()
    assert (row["produkt"], row["ml_total"]) == ("Bloom", 6.0)
    assert watering.get_recipe(conn, "Blüte") == []


def test_recipe_replace(conn):
    f, g = fert(conn), fert(conn, "Grow")
    watering.set_recipe(conn, "Wachstum", [(f, 1.0)])
    watering.set_recipe(conn, "Wachstum", [(g, 3.0)])
    r = watering.get_recipe(conn, "Wachstum")
    assert [(x.produkt, x.hersteller, x.ml_per_l) for x in r] == [("Grow", "BioBizz", 3.0)]


def test_watering_unknown_plant_raises(conn):
    a = plant(conn, 1)
    with pytest.raises(ValueError):
        watering.add_watering(conn, ts="2026-10-20T12:00", liters=2.0, items=[], plant_ids=[a, 99])
    assert conn.execute("SELECT COUNT(*) FROM watering").fetchone()[0] == 0


def test_set_recipe_unknown_fertilizer_raises(conn):
    with pytest.raises(ValueError):
        watering.set_recipe(conn, "Blüte", [(99, 2.0)])
