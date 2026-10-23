import asyncio
import json
import logging
import math
import os
import re
from datetime import date, datetime, time, timedelta

from . import calc, config, db, events, i18n, heatmap, phase_link, plants, report, sensors, settings, snapshot, stock, tasks
from .heatmap import VPD_TARGET
from .plants import BOX_PHASES
from .i18n import tr

log = logging.getLogger("growmi.jobs")
CATCH_UP_DAYS = 10  # matches the HA recorder's default retention


def last_box_phase(conn) -> str | None:
    row = conn.execute("SELECT phase FROM box_phase_change ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    return row["phase"] if row else None


def sync_box_phase(conn, ha, now: str) -> bool:
    current = config.state(ha, "phase")
    if current not in BOX_PHASES or current == last_box_phase(conn):
        return False
    conn.execute("INSERT INTO box_phase_change(ts, phase) VALUES (?,?)", (now, current))
    conn.commit()
    return True


# the freshly paired sensor reported -45.0 as its first value; drop readings no growbox can have
PLAUSIBLE = {"temp": (-10.0, 60.0), "rh": (0.0, 100.0), "vpd": (0.0, 6.0)}


def _clean(values, kind):
    lo, hi = PLAUSIBLE[kind]
    return [v for v in values if lo <= v <= hi]




def consumption(values: list[float]) -> float | None:
    """kWh used between the first and last reading of a total_increasing meter. A drop means the meter was
    reset (re-pairing, power loss): the new reading then counts as used since the reset."""
    if len(values) < 2:
        return None
    total, prev = 0.0, values[0]
    for v in values[1:]:
        total += v - prev if v >= prev else v
        prev = v
    return round(total, 3)


def _avg(values):
    return round(sum(values) / len(values), 2) if values else None


def _light_hours(ha) -> float | None:
    def secs(key):
        value = config.state(ha, key)
        if not value:
            return None
        hit = re.search(r"(\d{1,2}):(\d{2})", value)  # state may carry a date: '2026-10-20 06:00:00'
        return int(hit[1]) * 3600 + int(hit[2]) * 60 if hit else None

    an, aus = secs("light_on"), secs("light_off")
    if an is None or aus is None or an == aus:
        return None
    # shortcut: uses today's schedule helpers, not real switching history; upgrade if presets change mid-day
    return ((aus - an) % 86400) / 3600


def climate_summary(conn, ha, day: date, energy_entity: str | None = None) -> None:
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)
    t = _clean(config.history(ha, "temp", start, end), "temp")
    rh = _clean(config.history(ha, "rh", start, end), "rh")
    vpd = _clean(config.history(ha, "vpd", start, end), "vpd")
    if not (t or rh or vpd):
        return
    phase = conn.execute("SELECT phase FROM box_phase_change WHERE ts <= ? ORDER BY ts DESC, id DESC LIMIT 1",
                         (f"{day.isoformat()}T23:59",)).fetchone()
    name = phase["phase"] if phase else None
    lo, hi = VPD_TARGET.get(name, (None, None))
    ok_pct = round(100 * sum(lo <= v <= hi for v in vpd) / len(vpd), 1) if vpd and lo is not None else None
    kwh_values = ha.history(energy_entity, start, end) if energy_entity else []
    kwh = consumption(kwh_values)
    conn.execute(
        "INSERT OR REPLACE INTO climate_day(day, t_min, t_max, t_avg, rh_avg, vpd_avg, light_h, box_phase,"
        " vpd_ok_pct, kwh) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (day.isoformat(), min(t) if t else None, max(t) if t else None, _avg(t), _avg(rh), _avg(vpd),
         _light_hours(ha), name, ok_pct, kwh))
    conn.commit()


def catch_up_climate(conn, ha, today: date, energy_entity: str | None = None) -> None:
    stored = {r["day"] for r in conn.execute("SELECT day FROM climate_day")}
    for back in range(CATCH_UP_DAYS, 0, -1):
        day = today - timedelta(days=back)
        if day.isoformat() not in stored:
            climate_summary(conn, ha, day, energy_entity)


def water_reminders(conn, now: datetime, days: int = 4) -> list[str]:
    out = []
    for pid in plants.occupied_plants(conn, now.strftime("%Y-%m-%dT%H:%M")):
        p = conn.execute("SELECT slot, sorte, eingesetzt_am FROM plant WHERE id=?", (pid,)).fetchone()
        since = calc.days_since_water(conn, pid, now.date())
        if since is not None and since >= days:
            out.append(tr("Platz {slot} {sorte}: seit {n} Tagen nicht gegossen", slot=p["slot"], sorte=p["sorte"], n=since))
        elif since is None:
            planted = (now.date() - date.fromisoformat(p["eingesetzt_am"][:10])).days
            if planted >= days:
                out.append(tr("Platz {slot} {sorte}: noch nie gegossen (seit {n} Tagen im Zelt)", slot=p["slot"], sorte=p["sorte"], n=planted))
    return out


def photo_reminders(conn, now: datetime, days: int = 7) -> list[str]:
    out = []
    for pid in plants.occupied_plants(conn, now.strftime("%Y-%m-%dT%H:%M")):
        p = conn.execute("SELECT slot, sorte, eingesetzt_am FROM plant WHERE id=?", (pid,)).fetchone()
        last = conn.execute("SELECT MAX(ts) FROM photo WHERE plant_id=?", (pid,)).fetchone()[0]
        if last:
            age = (now.date() - date.fromisoformat(last[:10])).days
            if age >= days:
                out.append(tr("Platz {slot} {sorte}: seit {n} Tagen kein Foto", slot=p["slot"], sorte=p["sorte"], n=age))
        else:
            planted = (now.date() - date.fromisoformat(p["eingesetzt_am"][:10])).days
            if planted >= days:
                out.append(tr("Platz {slot} {sorte}: noch kein Foto (seit {n} Tagen im Zelt)", slot=p["slot"], sorte=p["sorte"], n=planted))
    return out


def _notify(ha, options: dict, title: str, message: str) -> None:
    ha.call_service("persistent_notification", "create",
                    {"title": title, "message": message, "notification_id": "growmi_water"})
    service = config.entity("notify") or options.get("notify_service") or ""
    if "." in service:
        domain, name = service.split(".", 1)
        ha.call_service(domain, name, {"title": title, "message": message})


def device_keys() -> set[str]:
    return {d["key"] for d in config.devices()}


def phase_week(conn, today: date) -> tuple[str, int] | None:
    """Current box phase and which week of it we are in, from the last recorded phase change."""
    row = conn.execute("SELECT ts, phase FROM box_phase_change ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return row["phase"], (today - date.fromisoformat(row["ts"][:10])).days // 7 + 1


def learned_interval(conn, now: datetime) -> float | None:
    since = (now - timedelta(days=30)).date().isoformat()
    days = sorted({r[0] for r in conn.execute("SELECT substr(ts,1,10) FROM watering WHERE substr(ts,1,10) >= ?", (since,))})
    if len(days) < 4:
        return None
    gaps = [(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(days, days[1:])]
    return sum(gaps) / len(gaps)


def reminder_days(conn, now: datetime, options: dict) -> int:
    """Remind after 1.5x the user's own usual watering gap, once there is enough history; else the fixed option."""
    mine = learned_interval(conn, now)
    if mine is None:
        return int(options.get("water_reminder_days") or 4)
    return min(max(math.ceil(mine * 1.5), 2), 10)


def on_hours(series: list, end: datetime, start: datetime | None = None) -> float:
    """Hours a switch was 'on', from [(datetime, state)] changes; clipped to [start, end]."""
    total = 0.0
    for (ts, state), nxt in zip(series, [t for t, _ in series[1:]] + [end]):
        if state == "on":
            begin = max(ts, start) if start else ts
            total += max((min(nxt, end) - begin).total_seconds(), 0) / 3600
    return total


def catch_up_devices(conn, ha, today: date) -> None:
    done = {(r["day"], r["device"]) for r in conn.execute("SELECT day, device FROM device_day")}
    for back in range(CATCH_UP_DAYS, 0, -1):
        day = today - timedelta(days=back)
        start = datetime.combine(day, time.min)
        for d in config.devices():
            key = d["key"]
            if (day.isoformat(), key) in done or not d.get("entity"):
                continue
            series = ha.history_states(d["entity"], start, start + timedelta(days=1))
            if series:
                conn.execute("INSERT OR REPLACE INTO device_day(day, device, hours) VALUES (?,?,?)",
                             (day.isoformat(), key, round(on_hours(series, start + timedelta(days=1), start), 2)))
    conn.commit()


def device_status(conn, today: date) -> list[dict]:
    out = []
    for d in config.devices():
        key, name, default_limit = d["key"], d.get("wear_name") or d["name"], d.get("wear_limit_h") or 10000.0
        w = conn.execute("SELECT * FROM wear WHERE device=?", (key,)).fetchone()
        limit = (w["limit_h"] if w and w["limit_h"] else default_limit)
        reset = w["reset_day"] if w and w["reset_day"] else "0000-00-00"
        hours = conn.execute("SELECT COALESCE(SUM(hours), 0) FROM device_day WHERE device=? AND day > ?", (key, reset)).fetchone()[0]
        pct = hours / limit * 100
        out.append({"key": key, "name": name, "hours": hours, "limit": limit, "pct": pct, "due": pct >= 90,
                    "reset_day": w["reset_day"] if w else None})
    return out


def set_wear_limit(conn, key: str, limit_h: float) -> None:
    conn.execute("INSERT INTO wear(device, limit_h) VALUES (?,?) ON CONFLICT(device) DO UPDATE SET limit_h=excluded.limit_h", (key, limit_h))
    conn.commit()


def reset_wear(conn, key: str, today: date) -> None:
    conn.execute("INSERT INTO wear(device, reset_day) VALUES (?,?) ON CONFLICT(device) DO UPDATE SET reset_day=excluded.reset_day",
                 (key, today.isoformat()))
    conn.commit()


def wear_reminders(conn, today: date) -> list[str]:
    return [tr("{name}: {pct:.0f} % der Lebensdauer ({hours:.0f} von {limit:.0f} h), bald tauschen", name=d["name"], pct=d["pct"], hours=d["hours"], limit=d["limit"])
            for d in device_status(conn, today) if d["due"]]


def stock_reminders(conn) -> list[str]:
    return [tr("{produkt}: Vorrat reicht noch ca. {n:.1f} Gießgänge (Rest {rest:.0f} ml)", produkt=s["produkt"], n=s["gaenge"], rest=s["rest_ml"])
            if s["gaenge"] is not None else tr("{produkt}: Vorrat leer", produkt=s["produkt"]) for s in stock.low_items(conn)]


def weather_hint(ha, options: dict, today: date) -> str | None:
    entity = options.get("weather_entity") or ha.find_entity("weather.")
    if not entity:
        return None
    resp = ha.call_service_response("weather", "get_forecasts", {"entity_id": entity, "type": "daily"})
    days = (((resp or {}).get("service_response") or {}).get(entity) or {}).get("forecast") or []
    tomorrow = (today + timedelta(days=1)).isoformat()
    temp = next((d.get("temperature") for d in days if str(d.get("datetime", ""))[:10] == tomorrow), None)
    if temp is not None and temp >= float(options.get("weather_hot_c") or 30):
        return tr("Morgen bis {t:g} °C draußen: das Zelt wird heiß. Abluft und Ventilator prüfen.", t=temp)
    return None


def in_quiet(now: datetime, options: dict) -> bool:
    qf, qt = options.get("quiet_from"), options.get("quiet_to")
    if not qf or not qt:
        return False
    mins = lambda s: int(s[:2]) * 60 + int(s[3:5])
    t, a, b = now.hour * 60 + now.minute, mins(qf), mins(qt)
    return a <= t < b if a < b else (t >= a or t < b)


def notify(ha, options: dict, conn, now: datetime, title: str, message: str, critical: bool = False) -> None:
    """Pushes now, or holds the message until the quiet hours end (critical ones always go out)."""
    if not critical and in_quiet(now, options):
        pending = json.loads(events.kv_get(conn, "pending.notify") or "[]")
        events.kv_set(conn, "pending.notify", json.dumps(pending + [message]))
        conn.commit()
        return
    _notify(ha, options, title, message)


def flush_pending(ha, options: dict, conn, now: datetime) -> None:
    pending = json.loads(events.kv_get(conn, "pending.notify") or "[]")
    if pending and not in_quiet(now, options):
        events.kv_set(conn, "pending.notify", "[]")
        conn.commit()
        _notify(ha, options, tr("Growmi"), "\n".join(pending))


def task_reminders(conn, today: date) -> list[str]:
    out = []
    for t in tasks.due_tasks(conn, today):
        late = (today - date.fromisoformat(t["due"])).days
        out.append(tr("Platz {slot} {sorte}: {title}", slot=t["slot"], sorte=t["sorte"], title=tr(t["title"])) + (tr(" (seit {n} Tagen fällig)", n=late) if late else ""))
    return out


def _step(name: str, fn) -> None:
    try:
        fn()
    except Exception:
        log.exception("job step %s failed", name)


def _maintenance(ha) -> bool:
    try:
        return config.state(ha, "maintenance") == "active"
    except Exception:
        return False


def run_once(db_path: str, ha, now: datetime, state: dict, options: dict | None = None) -> None:
    options = options or {}
    conn = db.connect(db_path)

    def climate():
        hour = now.strftime("%Y-%m-%d %H")
        if state.get("lang") != hour:  # HA's language can change, or HA was not ready at start
            state["lang"] = hour
            i18n.set_lang(config.current["lang"], ha.language())
        sync_box_phase(conn, ha, now.strftime("%Y-%m-%dT%H:%M"))
        key = now.strftime("%Y-%m-%d %H")  # retry missing days hourly, not every tick
        if state.get("catch_up") != key:
            catch_up_climate(conn, ha, now.date(), config.entity("energy") or options.get("energy_entity") or None)
            catch_up_devices(conn, ha, now.date())
            heatmap.catch_up_hours(conn, ha, now)
            state["catch_up"] = key

    def reminders():
        if now.hour >= 9 and state.get("reminded") != now.date():
            state["reminded"] = now.date()
            msgs = water_reminders(conn, now, reminder_days(conn, now, options)) + task_reminders(conn, now.date()) \
                + phase_link.reminder(conn, ha, now.date())
            last = state.get("photo_reminded")
            if last is None or (now.date() - last).days >= 7:  # photos are a weekly habit, don't nag daily
                photos = photo_reminders(conn, now)
                if photos:
                    state["photo_reminded"] = now.date()
                    msgs += photos
            last = state.get("care_reminded")
            if last is None or (now.date() - last).days >= 7:  # stock and wear change slowly: weekly is enough
                care = stock_reminders(conn) + wear_reminders(conn, now.date())
                if care:
                    state["care_reminded"] = now.date()
                    msgs += care
            if msgs:
                notify(ha, options, conn, now, tr("Growmi"), "\n".join(msgs))

    def extras():
        if now.hour >= 18 and state.get("weather") != now.date():
            state["weather"] = now.date()
            hint = weather_hint(ha, options, now.date())
            if hint:
                notify(ha, options, conn, now, tr("Wetter"), hint)
        week = now.isocalendar()[:2]
        if now.weekday() == 6 and now.hour >= 18 and state.get("report_week") != week:
            state["report_week"] = week
            notify(ha, options, conn, now, tr("Wochenbericht"), report.text(report.weekly(conn, now, settings.strompreis(ha, options))))

    try:
        _step("climate", climate)
        _step("events", lambda: events.detect_events(conn, ha, now))
        _step("tasks", lambda: tasks.generate_tasks(conn, now.date()))
        _step("sensors", lambda: sensors.publish(ha, conn, now, settings.strompreis(ha, options)))
        if not _maintenance(ha):  # no reminders while somebody works in the tent
            _step("flush", lambda: flush_pending(ha, options, conn, now))
            _step("reminders", reminders)
            _step("extras", extras)
        _step("backup", lambda: nightly(conn, db_path, options, state, now))
    finally:
        conn.close()


def nightly(conn, db_path: str, options: dict, state: dict, now: datetime) -> None:
    folder = options.get("backup_dir") or snapshot.DEFAULT_DIR
    if now.hour >= 3 and state.get("backup") != now.date() and os.path.isdir(os.path.dirname(folder.rstrip("/"))):
        state["backup"] = now.date()
        snapshot.snapshot(db_path, "nightly", keep=14, folder=folder)
        with open(os.path.join(folder, snapshot.LATEST), "w", encoding="utf-8") as f:
            f.write(snapshot.dump_json(conn))
        snapshot.mirror_photos(os.path.dirname(db_path), folder)


async def run_loop(db_path: str, ha, interval_s: int = 60, options: dict | None = None) -> None:
    state: dict = {}
    while True:
        await asyncio.to_thread(run_once, db_path, ha, datetime.now(), state, options)
        await asyncio.sleep(interval_s)
