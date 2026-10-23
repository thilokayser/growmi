from datetime import datetime, time, timedelta

from . import climate, config, events, jobs, phase_link, settings, tasks
from .i18n import tr

MODES = ("Auto", "Dauer an", "Dauer aus")
EXHAUST_MODES = ("Feuchteschutz", "Standard")


def _chart(ha, entity: str | None, title: str, unit: str, now: datetime) -> dict | None:
    if not entity:
        return None
    vals = ha.history(entity, now - timedelta(hours=24), now)
    if len(vals) < 2:
        return None
    return {"title": title, "unit": unit, "points": climate.polyline(vals, 300, 80), "min": min(vals), "max": max(vals),
            "first": tr("letzte 24 h"), "last": ""}


def build(ha, conn, options: dict, now: datetime) -> dict:
    temp = events._float(config.state(ha, "temp"))
    battery = events._float(config.state(ha, "battery"))
    online = config.state(ha, "online")
    mode = config.state(ha, "fan_mode")
    alerts = []
    if online == "off":
        alerts.append(tr("Klimasensor offline: Werte eingefroren, Klimaregelung gesperrt"))
    if battery is not None and battery < 25:
        alerts.append(tr("Batterie schwach ({pct:.0f} %)", pct=battery))
    if temp is not None and temp >= events.HEAT_ON:
        alerts.append(tr("Hitze: {t:.1f} °C", t=temp))
    if mode in ("Dauer an", "Dauer aus"):
        alerts.append(tr("Ventilator manuell: {mode}, Zeitschaltung pausiert", mode=tr(mode)))
    maintenance = config.state(ha, "maintenance") == "active"
    if maintenance:
        alerts.append(tr("Wartungsmodus aktiv: Abluft, Ventilator und Alarme pausieren"))
    alerts += jobs.water_reminders(conn, now, jobs.reminder_days(conn, now, options))
    energy = config.entity("energy") or options.get("energy_entity")
    kwh = None
    if energy:
        vals = ha.history(energy, datetime.combine(now.date(), time.min), now)
        kwh = jobs.consumption(vals)
    price = settings.strompreis(ha, options)
    return {
        "devices": [{"name": d["name"], "on": None if not d.get("entity") or (s := ha.state(d["entity"])) is None else s == "on"}
                    for d in config.devices()],
        "mode": mode, "modes": MODES, "exhaust_mode": config.state(ha, "exhaust_mode"), "exhaust_modes": EXHAUST_MODES, "maintenance": maintenance, "online": online,
        "battery": f"{battery:.0f}" if battery is not None else None,
        "has_fan": bool(config.entity("fan_mode")), "has_exhaust": bool(config.entity("exhaust_mode")),
        "has_maintenance": bool(config.entity("maintenance")), "has_battery": bool(config.entity("battery")),
        "alerts": alerts, "tasks": tasks.due_tasks(conn, now.date()),
        "charts": [c for c in (_chart(ha, config.entity("temp"), tr("Temperatur 24 h"), "°C", now),
                               _chart(ha, config.entity("vpd"), tr("VPD 24 h"), "kPa", now)) if c],
        "kwh": f"{kwh:.2f}" if kwh is not None else None,
        "eur": f"{kwh * price:.2f}" if kwh is not None and price > 0 else None,
        "events": events.list_events(conn, 8), "today_iso": now.date().isoformat(),
        "phase_suggestion": phase_link.suggestion(conn, ha, now.date()), "back": "/cockpit",
    }
