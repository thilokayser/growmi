from app import calc, plants, watering


def plant(conn, slot, sorte="S", keim="2026-09-01"):
    return plants.add_plant(conn, sorte=sorte, hersteller="H", keimdatum=keim, slot=slot,
                            phase="Wachstum", eingesetzt_am="2026-09-01T08:00")


def test_water_split_across_affected_plants(conn):
    a, b = plant(conn, 1), plant(conn, 2)
    watering.add_watering(conn, ts="2026-10-20T12:00", liters=4.0, items=[])
    assert calc.plant_totals(conn, a).water_l == 2.0
    assert calc.plant_totals(conn, b).water_l == 2.0


def test_water_over_lifetime_with_changing_occupancy(conn):
    a = plant(conn, 1)
    watering.add_watering(conn, ts="2026-10-01T12:00", liters=3.0, items=[], plant_ids=[a])
    b = plants.add_plant(conn, sorte="B", hersteller="H", keimdatum="2026-10-05", slot=2,
                         phase="Keimling", eingesetzt_am="2026-10-05T08:00")
    watering.add_watering(conn, ts="2026-10-10T12:00", liters=3.0, items=[])
    assert calc.plant_totals(conn, a).water_l == 4.5
    assert calc.plant_totals(conn, b).water_l == 1.5


def test_fert_sum_per_product(conn):
    a, b = plant(conn, 1), plant(conn, 2)
    bloom = watering.add_fertilizer(conn, "Bloom", "BB")
    grow = watering.add_fertilizer(conn, "Grow", "BB")
    watering.add_watering(conn, ts="2026-10-20T12:00", liters=2.0, items=[(bloom, 2.0), (grow, 1.0)])
    watering.add_watering(conn, ts="2026-10-21T12:00", liters=1.0, items=[(bloom, 4.0)])
    assert calc.plant_totals(conn, a).fert_ml == {"Bloom": 4.0, "Grow": 1.0}


def test_g_per_l_and_g_per_ml(conn):
    a = plant(conn, 1)
    f = watering.add_fertilizer(conn, "Bloom", "BB")
    watering.add_watering(conn, ts="2026-10-20T12:00", liters=5.0, items=[(f, 4.0)])
    plants.update_plant(conn, a, trocken_g=10.0)
    t = calc.plant_totals(conn, a)
    assert (t.trocken_g, t.g_per_l, t.g_per_ml) == (10.0, 2.0, 0.5)


def test_no_water_no_division_error(conn):
    a = plant(conn, 1)
    plants.update_plant(conn, a, trocken_g=10.0)
    t = calc.plant_totals(conn, a)
    assert (t.water_l, t.g_per_l, t.g_per_ml) == (0.0, None, None)


def test_no_harvest_gives_none(conn):
    a = plant(conn, 1)
    watering.add_watering(conn, ts="2026-10-20T12:00", liters=2.0, items=[])
    t = calc.plant_totals(conn, a)
    assert (t.trocken_g, t.g_per_l, t.g_per_ml) == (None, None, None)


def test_water_only_gives_no_g_per_ml(conn):
    a = plant(conn, 1)
    watering.add_watering(conn, ts="2026-10-20T12:00", liters=2.0, items=[])
    plants.update_plant(conn, a, trocken_g=4.0)
    assert calc.plant_totals(conn, a).g_per_ml is None


def test_by_sorte_groups_same_strain_across_runs(conn):
    a = plant(conn, 1, "Amnesia Haze", "2026-09-01")
    plants.finish_plant(conn, a, "2026-10-01T08:00", trocken_g=20.0)
    b = plant(conn, 1, "Amnesia Haze", "2026-10-02")
    c = plant(conn, 2, "Blue Dream")
    rows = calc.by_sorte(conn)
    assert [r.sorte for r in rows] == ["Amnesia Haze", "Blue Dream"]
    assert [t.plant_id for t in rows[0].plants] == [a, b]
    assert [t.plant_id for t in rows[1].plants] == [c]


def test_amounts_per_plant(conn):
    a, b = plant(conn, 1), plant(conn, 2)
    f = watering.add_fertilizer(conn, "Bloom", "BB", preis_eur=10, flasche_ml=1000)
    wid = watering.add_watering(conn, ts="2026-10-20T12:00", liters=0, items=[], plant_liters={a: 1.0, b: 3.0},
                                plant_ml={a: {f: 2.0}, b: {f: 5.0}})
    ta, tb = calc.plant_totals(conn, a), calc.plant_totals(conn, b)
    assert (ta.water_l, tb.water_l) == (1.0, 3.0)
    assert (ta.fert_ml, tb.fert_ml) == ({"Bloom": 2.0}, {"Bloom": 5.0})
    row = conn.execute("SELECT liters FROM watering").fetchone()
    item = conn.execute("SELECT ml_total, ml_per_l FROM watering_item").fetchone()
    assert (row[0], item[0], item[1]) == (4.0, 7.0, 7.0 / 4.0)
    # editing replaces the amounts but keeps the price recorded then
    conn.execute("UPDATE fertilizer SET preis_eur=99 WHERE id=?", (f,))
    watering.replace_amounts(conn, wid, {a: 2.0, b: 3.0}, {a: {f: 4.0}, b: {f: 5.0}})
    assert calc.plant_totals(conn, a).water_l == 2.0 and calc.plant_totals(conn, b).fert_ml == {"Bloom": 5.0}
    assert conn.execute("SELECT eur_per_ml FROM watering_item").fetchone()[0] == 0.01
    assert conn.execute("SELECT liters FROM watering").fetchone()[0] == 5.0


def test_old_equal_split_is_backfilled(conn):
    a, b = plant(conn, 1), plant(conn, 2)
    conn.execute("INSERT INTO watering(ts, liters) VALUES ('2026-10-20T12:00', 4.0)")
    conn.executemany("INSERT INTO watering_plant(watering_id, plant_id) VALUES (1, ?)", [(a,), (b,)])
    conn.execute("INSERT INTO watering_item(watering_id, produkt, hersteller, ml_per_l, ml_total) VALUES (1,'X','',2,8)")
    from app import db
    db.backfill_shares(conn)
    db.backfill_shares(conn)  # runs on every start: must not double the rows
    assert calc.plant_totals(conn, a).water_l == 2.0 and calc.plant_totals(conn, b).fert_ml == {"X": 4.0}
