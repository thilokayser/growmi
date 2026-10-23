"""Populated app state and the pages worth rendering, shared by tests that look at every page."""
import re
from datetime import datetime, timedelta

from app import plants, tasks

NOW = datetime.now()


def norm(html: str) -> str:
    html = re.sub(r"\d\d:\d\d(:\d\d)?", "HH:MM", html)
    html = re.sub(r"\s+", " ", html)
    return re.sub(r"> <", "><", html)


def populate(web) -> list[int]:
    c = web.conn()
    ids = []
    for slot, (sorte, phase, typ) in enumerate([("Alpha", "Wachstum", "photo"), ("Beta", "Blüte", "auto"), ("Gamma", "Keimling", None)], 1):
        day = (NOW - timedelta(days=20 * slot)).strftime("%Y-%m-%dT08:00")
        ids.append(plants.add_plant(c, sorte=sorte, hersteller="Herst", keimdatum=day[:10], slot=slot, phase=phase,
                                    eingesetzt_am=day, typ=typ, notiz="n"))
    c.execute("INSERT INTO fertilizer(produkt, hersteller, n, p, k, preis_eur, flasche_ml, bestand_ml, bestand_ab) VALUES ('Compo','Compo',3,1,5,9.9,1000,500,?)", (NOW.isoformat(),))
    c.execute("INSERT INTO recipe_item(box_phase, fertilizer_id, ml_per_l) VALUES ('Wachstum',1,2.0)")
    for d in range(6):
        ts = (NOW - timedelta(days=d * 3)).strftime("%Y-%m-%dT09:00")
        c.execute("INSERT INTO watering(ts, liters, ph, ec) VALUES (?,3.0,6.2,1.4)", (ts,))
        for pid in ids:
            c.execute("INSERT INTO watering_plant(watering_id, plant_id) VALUES (?,?)", (d + 1, pid))
        c.execute("INSERT INTO watering_item(watering_id, produkt, hersteller, ml_per_l, ml_total, eur_per_ml) VALUES (?,'Compo','Compo',2,6,0.01)", (d + 1,))
    c.execute("INSERT INTO intervention(ts, plant_id, art, text, tag) VALUES (?,?,'Topping','oben','Stress')", (NOW.strftime("%Y-%m-%dT10:00"), ids[0]))
    c.execute("INSERT INTO photo(ts, plant_id, filename) VALUES (?,?,'x.jpg')", (NOW.strftime("%Y-%m-%dT10:00"), ids[0]))
    c.execute("INSERT INTO box_event(ts, kind, text) VALUES (?,'hitze','Hitze: 30.1 °C')", (NOW.strftime("%Y-%m-%dT10:00"),))
    c.execute("INSERT INTO box_phase_change(ts, phase) VALUES (?, 'Wachstum')", ((NOW - timedelta(days=30)).strftime("%Y-%m-%dT08:00"),))
    c.execute("INSERT INTO climate_day(day, t_min, t_max, t_avg, rh_avg, vpd_avg, light_h, box_phase, vpd_ok_pct, kwh) VALUES (?,20,28,24,60,1.0,18,'Wachstum',80,2.5)", ((NOW - timedelta(days=1)).strftime("%Y-%m-%d"),))
    c.commit()
    tasks.generate_tasks(c, NOW.date())
    c.commit()
    web.ha.states.update({"sensor.growbox_temperatur": "30.4", "sensor.growbox_vpd": "1.9", "sensor.growbox_luftfeuchtigkeit": "55",
                          "input_select.grow_phase": "Wachstum", "binary_sensor.growbox_sensor_online": "off",
                          "sensor.growbox_batterie": "12", "input_select.grow_ventilator_modus": "Dauer an"})
    return ids


def paths(ids: list[int]) -> list[str]:
    return ["/", "/cockpit", "/verlauf", "/auswertung", "/einkauf", "/bericht", "/planung", "/probleme", "/stammdaten/wochenplan",
            "/verschleiss", "/pflanze/neu", "/giessen", "/notiz", "/foto", "/fotos", "/heatmap", "/stammdaten",
            "/stammdaten/duenger/1", "/wiederherstellen", "/platz/1", "/platz/2", "/qr", "/kiosk", "/einstellungen"] \
        + [f"/pflanze/{i}" for i in ids] + [f"/pflanze/{i}/schnell" for i in ids]
