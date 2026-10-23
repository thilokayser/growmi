"""Install-specific settings (which HA entities, devices, plants slots). Stored as JSON in kv['config'];
`current` is what the rest of the app reads. Empty values mean 'not set': that feature stays hidden."""
import copy
import json

from .i18n import tr
from .i18n_en import EN

SLOT_MIN, SLOT_MAX = 1, 8
ENTITY_KEYS = ("temp", "rh", "vpd", "online", "battery", "phase", "light_on", "light_off", "fan_mode",
               "exhaust_mode", "maintenance", "price", "energy", "notify", "phase_script")
ROLES = ("", "licht", "abluft", "ventilator")

EMPTY = {**dict.fromkeys(ENTITY_KEYS, ""), "lang": "", "phase_link": False, "phase_light_on": "08:00:00",
         "phase_light_off": "20:00:00", "devices": [], "slots": ["", "", "", ""]}  # empty = default name, resolved in the current language

# a complete sample configuration: documents the keys, and the tests run on it
EXAMPLE = {**EMPTY,
          "temp": "sensor.growbox_temperatur", "rh": "sensor.growbox_luftfeuchtigkeit", "vpd": "sensor.growbox_vpd",
          "online": "binary_sensor.growbox_sensor_online", "battery": "sensor.growbox_batterie",
          "phase": "input_select.grow_phase", "light_on": "input_datetime.grow_licht_an",
          "light_off": "input_datetime.grow_licht_aus", "fan_mode": "input_select.grow_ventilator_modus",
          "exhaust_mode": "input_select.grow_abluft_modus", "maintenance": "timer.grow_wartung",
          "price": "input_number.growbox_strompreis", "phase_script": "script.grow_licht_preset",
          "lang": "de", "phase_link": True,
          "devices": [{"key": "lampe", "name": "Licht", "wear_name": "Lampe", "entity": "switch.grow_light",
                       "wear_limit_h": 25000.0, "role": "licht"},
                      {"key": "akf", "name": "Abluft", "wear_name": "AKF-Filter (Abluft)", "entity": "switch.grow_exhaust",
                       "wear_limit_h": 4000.0, "role": "abluft"},
                      {"key": "ventilator", "name": "Ventilator", "wear_name": "Ventilator", "entity": "switch.grow_fan",
                       "wear_limit_h": 30000.0, "role": "ventilator"}],
          "slots": ["vorne links", "vorne rechts", "hinten links", "hinten rechts"]}

current: dict = copy.deepcopy(EMPTY)


def _kv_get(conn, key):
    row = conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else None


def load(conn) -> dict:
    global current
    raw = _kv_get(conn, "config")
    current = {**copy.deepcopy(EMPTY), **(json.loads(raw) if raw else {})}
    return current


def _validate(data: dict, conn) -> None:
    n = len(data["slots"])
    if not SLOT_MIN <= n <= SLOT_MAX:
        raise ValueError(tr("Anzahl Plätze muss {lo} bis {hi} sein", lo=SLOT_MIN, hi=SLOT_MAX))
    busy = [r["slot"] for r in conn.execute("SELECT slot FROM plant WHERE ausgezogen_am IS NULL AND slot > ?", (n,))]
    if busy:
        raise ValueError(tr("Platz {n} ist noch belegt, erst die Pflanze ausziehen oder verschieben", n=min(busy)))
    for key in ENTITY_KEYS:
        value = data[key]
        if value and not (value.count(".") == 1 and all(value.split("."))):
            raise ValueError(tr("{key}: {value} ist keine Entity-ID (Form domain.name)", key=key, value=repr(value)))
    if data["lang"] not in ("", "de", "en"):
        raise ValueError(tr("Unbekannte Sprache: {lang}", lang=data["lang"]))
    for d in data["devices"]:
        if d["role"] not in ROLES:
            raise ValueError(tr("Unbekannte Rolle: {role}", role=d["role"]))


def save(conn, data: dict) -> None:
    global current
    full = {**copy.deepcopy(EMPTY), **data}
    _validate(full, conn)
    conn.execute("INSERT INTO kv(k, v) VALUES ('config', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                 (json.dumps(full, ensure_ascii=False),))
    conn.commit()
    current = full


def entity(key: str) -> str | None:
    return current.get(key) or None


def state(ha, key: str):
    e = entity(key)
    return ha.state(e) if e else None


def history(ha, key: str, start, end) -> list:
    e = entity(key)
    return ha.history(e, start, end) if e else []


def role_entity(role: str) -> str | None:
    return next((d["entity"] for d in current["devices"] if d["role"] == role and d["entity"]), None)


def devices() -> list[dict]:
    return current["devices"]


def is_default_slot_name(name: str, number: int) -> bool:
    """'Platz 2' / 'Spot 2': the generated names, whichever language they were typed in."""
    return name in ("Platz {n}".format(n=number), EN["Platz {n}"].format(n=number))


def slot_names() -> list[str]:
    return [n or tr("Platz {n}", n=i) for i, n in enumerate(current["slots"], 1)]


def slots() -> dict[int, str]:
    return dict(enumerate(slot_names(), 1))


def slot_label(slot: int) -> str:
    """'Platz 2 · vorne links'; a slot without its own name is just 'Platz 2'."""
    own = current["slots"][slot - 1] if 0 < slot <= len(current["slots"]) else ""
    return tr("Platz {n}", n=slot) + (f" · {own}" if own else "")


def slot_count() -> int:
    return len(current["slots"])
