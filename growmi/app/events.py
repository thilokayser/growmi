import re

from . import config
from .plants import now_ts
from .i18n import tr

HEAT_ON, HEAT_OFF, FAN_ON, FAN_OFF = 29.0, 28.0, 26.0, 24.0


def kv_get(conn, key: str) -> str | None:
    row = conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else None


def kv_set(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO kv(k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))


def add_event(conn, ts: str, kind: str, text: str) -> None:
    conn.execute("INSERT INTO box_event(ts, kind, text) VALUES (?,?,?)", (ts, kind, text))
    conn.commit()


def list_events(conn, limit: int = 30, since: str | None = None) -> list:
    where, args = ("WHERE ts >= ?", (since, limit)) if since else ("", (limit,))
    return conn.execute(f"SELECT * FROM box_event {where} ORDER BY ts DESC, id DESC LIMIT ?", args).fetchall()


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def detect_events(conn, ha, now) -> None:
    """Turns state changes in HA into diary entries for the box. The first run only learns the current state."""
    ts = now.strftime("%Y-%m-%dT%H:%M")
    from .jobs import _light_hours  # late import: jobs imports this module

    online = config.state(ha, "online")
    if online in ("on", "off"):
        before = kv_get(conn, "ev.online")
        if before and before != online:
            add_event(conn, ts, "sensor", tr("Klimasensor wieder online") if online == "on" else tr("Klimasensor offline"))
        kv_set(conn, "ev.online", online)

    t = _float(config.state(ha, "temp"))
    if t is not None:
        for key, kind, start, end, low, high, label in (
                ("ev.hitze", "hitze", HEAT_ON, HEAT_OFF, tr("Hitze vorbei"), tr("Hitze"), tr("Schwelle 29 °C")),
                ("ev.fan", "ventilator", FAN_ON, FAN_OFF, tr("Ventilator-Hitzeregel beendet"),
                 tr("Ventilator-Hitzeregel aktiv ab 26 °C"), None)):
            active = kv_get(conn, key) == "1"
            if not active and t >= start:
                text = f"{high}: {t:.1f} °C ({label})" if label else f"{high} ({t:.1f} °C)"
                add_event(conn, ts, kind, text)
                kv_set(conn, key, "1")
            elif active and t < end:
                add_event(conn, ts, kind if kind == "ventilator" else "hitze_ende", f"{low}: {t:.1f} °C")
                kv_set(conn, key, "0")

    an, aus = config.state(ha, "light_on"), config.state(ha, "light_off")
    if an and aus:
        cycle = f"{an[:5]}-{aus[:5]}"
        before = kv_get(conn, "ev.licht")
        if before and before != cycle:
            h = _light_hours(ha)
            add_event(conn, ts, "licht", tr("Lichtzyklus {h:g}/{rest:g} (an {an}, aus {aus})", h=h, rest=24 - h, an=an[:5], aus=aus[:5])
                      if h else tr("Lichtzyklus (an {an}, aus {aus})", an=an[:5], aus=aus[:5]))
        kv_set(conn, "ev.licht", cycle)

    mode = config.state(ha, "fan_mode")
    if mode:
        before = kv_get(conn, "ev.modus")
        if before and before != mode:
            add_event(conn, ts, "ventilator", tr("Ventilator-Modus: {mode}", mode=tr(mode)))
        kv_set(conn, "ev.modus", mode)
    ex = config.state(ha, "exhaust_mode")
    if ex:
        before = kv_get(conn, "ev.abluft_modus")
        if before and before != ex:
            add_event(conn, ts, "abluft", tr("Abluft-Modus: {mode}", mode=tr(ex)))
        kv_set(conn, "ev.abluft_modus", ex)
    conn.commit()
