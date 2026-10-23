from datetime import date, datetime

from . import config, events, plants, tasks
from .i18n import tr

ORDER = plants.BOX_PHASES


def suggestion(conn, ha, today: date) -> dict | None:
    """Photoperiod plants already in a later phase than the box: offer to move the box (and light) along."""
    box = config.state(ha, "phase")
    if not config.current["phase_link"] or box not in ORDER or events.kv_get(conn, "suggest.snooze") == today.isoformat():
        return None
    ahead, auto_present = [], False
    for pid in plants.occupied_plants(conn, datetime.now().strftime("%Y-%m-%dT%H:%M")):
        p = conn.execute("SELECT * FROM plant WHERE id=?", (pid,)).fetchone()
        phase = plants.current_phase(conn, pid)
        if tasks.is_auto(p):
            auto_present = True
        elif phase in ORDER and ORDER.index(phase) > ORDER.index(box):
            ahead.append((ORDER.index(phase), p["sorte"]))
    if not ahead:
        return None
    return {"target": ORDER[max(i for i, _ in ahead)], "box": box, "names": [n for _, n in ahead],
            "auto_present": auto_present}


def snooze(conn, today: date) -> None:
    events.kv_set(conn, "suggest.snooze", today.isoformat())
    conn.commit()


def apply(ha, conn, target: str, with_light: bool, now: datetime) -> bool:
    if not config.entity("phase") or not ha.call_service("input_select", "select_option",
                                                         {"entity_id": config.entity("phase"), "option": target}):
        return False
    script = config.entity("phase_script")
    light = with_light and target == "Blüte" and bool(script)
    if light and not ha.call_service(*script.split("."), {"an": config.current["phase_light_on"],
                                                           "aus": config.current["phase_light_off"]}):
        events.add_event(conn, now.strftime("%Y-%m-%dT%H:%M"), "phase",
                         tr("Box-Phase auf {target} umgestellt, Lichtwechsel fehlgeschlagen", target=tr(target)))
        return False
    events.add_event(conn, now.strftime("%Y-%m-%dT%H:%M"), "phase",
                     tr("Box-Phase auf {target} umgestellt", target=tr(target)) + (tr(" (Licht 12/12)") if light else ""))
    return True


def reminder(conn, ha, today: date) -> list[str]:
    s = suggestion(conn, ha, today)
    if not s:
        return []
    return [tr("{names} in {target}, die Box-Phase steht noch auf {box}. Im Tagebuch auf dem Cockpit umstellen.",
               names=", ".join(s["names"]), target=tr(s["target"]), box=tr(s["box"]))]
