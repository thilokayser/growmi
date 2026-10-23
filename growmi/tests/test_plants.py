import pytest

from app import plants


def mk(conn, slot=1, sorte="Northern Lights", phase="Keimling", **kw):
    return plants.add_plant(conn, sorte=sorte, hersteller="Sensi Seeds", keimdatum="2026-10-01",
                            slot=slot, phase=phase, **kw)


def test_add_plant_creates_first_phase(conn):
    pid = mk(conn, eingesetzt_am="2026-10-01T08:00")
    assert plants.current_phase(conn, pid) == "Keimling"


def test_slot_taken_raises(conn):
    mk(conn, slot=1)
    with pytest.raises(plants.SlotTaken):
        mk(conn, slot=1, sorte="Andere")


def test_slot_free_after_finish_and_history_kept(conn):
    a = mk(conn, slot=1)
    plants.finish_plant(conn, a, "2026-12-01T10:00", trocken_g=30.0)
    assert plants.slot_occupant(conn, 1) is None
    b = mk(conn, slot=1, sorte="Neue")
    assert plants.slot_occupant(conn, 1) == b
    assert plants.current_phase(conn, a) == "Geerntet"
    assert conn.execute("SELECT trocken_g FROM plant WHERE id=?", (a,)).fetchone()[0] == 30.0


def test_phase_history_orders_by_ab(conn):
    pid = mk(conn, eingesetzt_am="2026-10-01T08:00")
    plants.set_phase(conn, pid, "Blüte", "2026-11-01T08:00")
    plants.set_phase(conn, pid, "Wachstum", "2026-10-10T08:00")
    assert plants.current_phase(conn, pid) == "Blüte"


def test_occupied_plants_in_past(conn):
    pid = mk(conn, eingesetzt_am="2026-10-01T08:00")
    plants.finish_plant(conn, pid, "2026-10-10T08:00")
    assert plants.occupied_plants(conn, "2026-10-05T12:00") == [pid]
    assert plants.occupied_plants(conn, "2026-10-12T12:00") == []
    assert plants.occupied_plants(conn, "2026-09-30T12:00") == []


@pytest.mark.parametrize("slot", [0, 5])
def test_invalid_slot_rejected(conn, slot):
    with pytest.raises(ValueError):
        mk(conn, slot=slot)


def test_invalid_phase_rejected(conn):
    with pytest.raises(ValueError):
        mk(conn, phase="Quatsch")
    pid = mk(conn)
    with pytest.raises(ValueError):
        plants.set_phase(conn, pid, "Quatsch", "2026-10-02T08:00")


def test_update_plant_fields(conn):
    pid = mk(conn)
    plants.update_plant(conn, pid, sorte="Neu", trocken_g=12.5)
    row = conn.execute("SELECT sorte, trocken_g FROM plant WHERE id=?", (pid,)).fetchone()
    assert (row["sorte"], row["trocken_g"]) == ("Neu", 12.5)
    with pytest.raises(ValueError):
        plants.update_plant(conn, pid, id=99)


def test_parse_decimal():
    assert plants.parse_decimal("2,5") == 2.5
    assert plants.parse_decimal(" 3.25 ") == 3.25
    for bad in ("0", "-1", "abc", "", "nan"):
        with pytest.raises(ValueError):
            plants.parse_decimal(bad)


def test_norm_ts_and_norm_date():
    assert plants.norm_ts("2026-10-20T12:05") == "2026-10-20T12:05"
    assert plants.norm_ts("2026-10-20T12:05:33") == "2026-10-20T12:05"
    assert len(plants.norm_ts("")) == 16
    for bad in ("gestern", "2026-13-40T99:00"):
        with pytest.raises(ValueError):
            plants.norm_ts(bad)
    assert plants.norm_date("2026-10-20") == "2026-10-20"
    assert plants.norm_date(" ") is None
    with pytest.raises(ValueError):
        plants.norm_date("20.10.2026")


def test_delete_plant_cascades_and_returns_photo_names(conn):
    from app import entries, watering
    a, b = mk(conn, slot=1), mk(conn, slot=2, sorte="B")
    entries.add_intervention(conn, ts="2026-10-02T08:00", plant_id=a, art="LST")
    entries.add_photo(conn, ts="2026-10-02T08:00", plant_id=a, filename="a.jpg")
    solo = watering.add_watering(conn, ts="2026-10-03T08:00", liters=1.0, items=[], plant_ids=[a])
    shared = watering.add_watering(conn, ts="2026-10-03T09:00", liters=2.0, items=[], plant_ids=[a, b])
    assert plants.delete_plant(conn, a) == ["a.jpg"]
    assert conn.execute("SELECT COUNT(*) FROM plant").fetchone()[0] == 1
    for t in ("plant_phase", "intervention", "photo"):
        assert conn.execute(f"SELECT COUNT(*) FROM {t} WHERE plant_id=?", (a,)).fetchone()[0] == 0
    left = [r[0] for r in conn.execute("SELECT id FROM watering")]
    assert left == [shared] and solo not in left


def test_move_plant_checks_occupancy(conn):
    a, b = mk(conn, slot=1), mk(conn, slot=2, sorte="B")
    with pytest.raises(plants.SlotTaken):
        plants.move_plant(conn, a, 2)
    with pytest.raises(ValueError):
        plants.move_plant(conn, a, 7)
    plants.move_plant(conn, a, 3)
    assert plants.slot_occupant(conn, 3) == a
    plants.finish_plant(conn, b, "2026-12-01T10:00")
    plants.move_plant(conn, b, 1)  # finished plants may sit on any slot in the archive


def test_delete_phase_keeps_last(conn):
    pid = mk(conn, eingesetzt_am="2026-10-01T08:00")
    plants.set_phase(conn, pid, "Wachstum", "2026-10-10T08:00")
    ids = [r[0] for r in conn.execute("SELECT id FROM plant_phase WHERE plant_id=? ORDER BY ab", (pid,))]
    plants.delete_phase(conn, ids[1])
    assert plants.current_phase(conn, pid) == "Keimling"
    with pytest.raises(ValueError):
        plants.delete_phase(conn, ids[0])
