from datetime import datetime

from . import calc, plants, tasks
from .i18n import tr

PHASE_KEYS = {"Keimling": "keimling", "Wachstum": "wachstum", "Blüte": "bluete", "Trocknung": "trocknung"}


def build_sensors(conn, now: datetime, strompreis: float) -> dict:
    """entity_id -> (state, attributes) for virtual HA sensors that summarise the diary."""
    today = now.date()
    occupied = plants.occupied_plants(conn, now.strftime("%Y-%m-%dT%H:%M"))
    last = conn.execute("SELECT MAX(ts) FROM watering").fetchone()[0]
    days = (today - datetime.fromisoformat(last[:10]).date()).days if last else "unknown"
    counts = dict.fromkeys(PHASE_KEYS.values(), 0)
    ages = []
    for pid in occupied:
        p = conn.execute("SELECT keimdatum, eingesetzt_am FROM plant WHERE id=?", (pid,)).fetchone()
        counts[PHASE_KEYS.get(plants.current_phase(conn, pid), "trocknung")] += 1
        ages.append((today - datetime.fromisoformat((p["keimdatum"] or p["eingesetzt_am"])[:10]).date()).days)
    cost = sum(calc.plant_totals(conn, r["id"], strompreis).cost_eur or 0
               for r in conn.execute("SELECT id FROM plant"))
    return {
        "sensor.growmi_tage_seit_giessen": (days, {"friendly_name": tr("Tage seit letztem Gießen"),
                                                    "unit_of_measurement": "d", "icon": "mdi:watering-can"}),
        "sensor.growmi_pflanzen": (len(occupied), {"friendly_name": tr("Pflanzen im Zelt"), "icon": "mdi:sprout", **counts}),
        "sensor.growmi_grow_woche": (max(ages) // 7 + 1 if ages else "unknown",
                                      {"friendly_name": tr("Grow-Woche (älteste Pflanze)"), "icon": "mdi:calendar-week",
                                       "tage": max(ages) if ages else None}),
        "sensor.growmi_kosten": (round(cost, 2), {"friendly_name": tr("Grow-Kosten bisher"), "unit_of_measurement": "€",
                                                   "icon": "mdi:cash"}),
        "sensor.growmi_aufgaben": (len(tasks.due_tasks(conn, today)),
                                    {"friendly_name": tr("Fällige Aufgaben"), "icon": "mdi:checkbox-marked-circle-outline"}),
    }


def publish(ha, conn, now: datetime, strompreis: float) -> None:
    for entity, (state, attrs) in build_sensors(conn, now, strompreis).items():
        ha.set_state(entity, state, attrs)
