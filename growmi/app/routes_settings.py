import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from . import config, i18n, plants
from .i18n import tr
from .web import get_conn, redirect, render
from .i18n import tr

router = APIRouter()
ENTITY = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
TIME = re.compile(r"^\d\d:\d\d(:\d\d)?$")
# which HA domains each pick list offers
LISTS = {"sensor": ("sensor", "input_number"), "binary": ("binary_sensor",), "select": ("input_select",),
         "datetime": ("input_datetime",), "timer": ("timer",), "script": ("script",), "switch": ("switch",)}


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "geraet"
    key, n = base, 2
    while key in taken:
        key, n = f"{base}-{n}", n + 1
    return key


def _time(value: str, fallback: str) -> str:
    value = (value or "").strip() or fallback
    if not TIME.match(value):
        raise ValueError(tr("Uhrzeit ungültig: {value}", value=value))
    return value if len(value) == 8 else value + ":00"


def parse(form) -> dict:
    data = {k: (form.get(k) or "").strip() for k in config.ENTITY_KEYS}
    data["lang"] = (form.get("lang") or "").strip()
    data["phase_link"] = form.get("phase_link") == "on"
    data["phase_light_on"] = _time(form.get("phase_light_on"), "08:00:00")
    data["phase_light_off"] = _time(form.get("phase_light_off"), "20:00:00")
    lines = [line.strip() for line in (form.get("slots") or "").splitlines() if line.strip()]
    data["slots"] = ["" if config.is_default_slot_name(name, i) else name for i, name in enumerate(lines, 1)]  # default names stay language-neutral
    rows = zip(*(form.getlist(f"dev_{f}") for f in ("key", "name", "wear_name", "entity", "role", "limit")))
    devices, taken = [], set()
    for key, name, wear, entity, role, limit in rows:
        name, entity = name.strip(), entity.strip()
        if not name and not entity:
            continue  # an emptied row removes the device
        key = key.strip() or _slug(name or entity, taken)
        taken.add(key)
        devices.append({"key": key, "name": name or entity, "wear_name": wear.strip(), "entity": entity,
                        "role": role.strip(), "wear_limit_h": plants.parse_decimal(limit) if limit.strip() else None})
    data["devices"] = devices
    return data


def _page(request: Request, cfg: dict, status=200, error=None, saved=False):
    ids = request.app.state.ha.all_states()
    lists = {name: [i for i in ids if i.split(".")[0] in domains] for name, domains in LISTS.items()}
    slot_text = "\n".join(n or tr("Platz {n}", n=i) for i, n in enumerate(cfg["slots"], 1))
    return render(request, "einstellungen.html", status, cfg=cfg, lists=lists, error=error, saved=saved, slot_text=slot_text,
                  roles=config.ROLES, spare=range(2))


@router.get("/einstellungen")
def page(request: Request, saved: int = 0):
    return _page(request, config.current, saved=bool(saved))


@router.post("/einstellungen")
async def save(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    try:
        config.save(conn, parse(form))
        i18n.set_lang(config.current["lang"], request.app.state.ha.language())
    except ValueError as e:
        try:
            shown = {**config.current, **parse(form)}
        except ValueError:
            shown = config.current
        return _page(request, shown, 400, str(e))
    return redirect(request, "/einstellungen?saved=1")


@router.get("/einstellungen/test")
def test_entity(request: Request, entity: str = ""):
    if not ENTITY.match(entity):
        return JSONResponse({"ok": False, "state": None}, status_code=400)
    state = request.app.state.ha.state(entity)
    return {"ok": state is not None, "state": state}
