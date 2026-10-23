from datetime import date, datetime

from app import jobs
from tests.conftest import FakeHA

PHASE = "input_select.grow_phase"
T, RH, VPD = "sensor.growbox_temperatur", "sensor.growbox_luftfeuchtigkeit", "sensor.growbox_vpd"


def rows(conn, table="box_phase_change"):
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]


def test_first_sync_stores_current_phase(conn):
    assert jobs.sync_box_phase(conn, FakeHA(states={PHASE: "Wachstum"}), "2026-10-20T12:00") is True
    assert jobs.last_box_phase(conn) == "Wachstum"


def test_sync_writes_row_only_on_change(conn):
    ha = FakeHA(states={PHASE: "Wachstum"})
    jobs.sync_box_phase(conn, ha, "2026-10-20T12:00")
    assert jobs.sync_box_phase(conn, ha, "2026-10-20T12:01") is False
    ha.states[PHASE] = "Blüte"
    assert jobs.sync_box_phase(conn, ha, "2026-10-21T08:00") is True
    assert [r["phase"] for r in rows(conn)] == ["Wachstum", "Blüte"]


def test_sync_ignores_unavailable_and_invalid(conn):
    for value in (None, "Quatsch"):
        assert jobs.sync_box_phase(conn, FakeHA(states={PHASE: value}), "2026-10-20T12:00") is False
    assert rows(conn) == []


def ha_with_day(temps=(20.0, 24.0, 22.0)):
    return FakeHA(
        states={"input_datetime.grow_licht_an": "06:00:00", "input_datetime.grow_licht_aus": "00:00:00"},
        histories={T: list(temps), RH: [60.0, 70.0], VPD: [0.8, 1.0]})


def test_climate_summary_values(conn):
    conn.execute("INSERT INTO box_phase_change(ts, phase) VALUES ('2026-10-01T08:00', 'Wachstum')")
    jobs.climate_summary(conn, ha_with_day(), date(2026, 10, 19))
    r = rows(conn, "climate_day")[0]
    assert (r["day"], r["t_min"], r["t_max"], r["t_avg"]) == ("2026-10-19", 20.0, 24.0, 22.0)
    assert (r["rh_avg"], r["vpd_avg"], r["box_phase"]) == (65.0, 0.9, "Wachstum")


def test_light_hours_wraps_midnight(conn):
    jobs.climate_summary(conn, ha_with_day(), date(2026, 10, 19))
    assert rows(conn, "climate_day")[0]["light_h"] == 18.0


def test_climate_no_data_writes_nothing(conn):
    jobs.climate_summary(conn, FakeHA(), date(2026, 10, 19))
    assert rows(conn, "climate_day") == []


def test_catch_up_fills_missing_days_up_to_yesterday_capped_at_10(conn):
    conn.execute("INSERT INTO climate_day(day) VALUES ('2026-10-18')")
    jobs.catch_up_climate(conn, ha_with_day(), date(2026, 10, 20))
    days = [r["day"] for r in rows(conn, "climate_day")]
    assert days == [f"2026-10-{d:02d}" for d in range(10, 20)]


def test_catch_up_is_idempotent(conn):
    ha = ha_with_day()
    jobs.catch_up_climate(conn, ha, date(2026, 10, 20))
    first = rows(conn, "climate_day")
    calls = len(ha.history_calls)
    jobs.catch_up_climate(conn, ha, date(2026, 10, 20))
    assert rows(conn, "climate_day") == first
    assert len(ha.history_calls) == calls


class Boom:
    def state(self, *a):
        raise RuntimeError("HA down")

    history = state


def test_run_once_survives_ha_errors(tmp_path):
    from app import db
    path = str(tmp_path / "x.db")
    c = db.connect(path); db.init_schema(c); c.close()
    jobs.run_once(path, Boom(), datetime(2026, 10, 20, 12, 0), {})


def test_light_hours_accepts_datetime_states(conn):
    ha = ha_with_day()
    ha.states = {"input_datetime.grow_licht_an": "2026-10-20 06:00:00",
                 "input_datetime.grow_licht_aus": "2026-10-20 00:00:00"}
    jobs.climate_summary(conn, ha, date(2026, 10, 19))
    assert rows(conn, "climate_day")[0]["light_h"] == 18.0


def test_climate_summary_ignores_implausible_sensor_values(conn):
    ha = ha_with_day(temps=(-45.0, 22.0, 24.0))
    ha.histories[RH] = [0.0, 60.0, 250.0]
    jobs.climate_summary(conn, ha, date(2026, 10, 19))
    r = rows(conn, "climate_day")[0]
    assert (r["t_min"], r["t_max"], r["t_avg"]) == (22.0, 24.0, 23.0)
    assert r["rh_avg"] == 30.0  # 0 % is a valid reading, 250 % is not
