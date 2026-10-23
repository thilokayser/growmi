import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config, db, i18n, plants, snapshot

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))


def fmt_dt(value: str | None) -> str:
    """'2026-08-22T08:00' -> '22.08.2026 08:00'; a bare date stays a date."""
    if not value:
        return "–"
    value = value if isinstance(value, str) else value.isoformat()
    day, _, clock = value.partition("T")
    y, m, d = day.split("-")
    return f"{d}.{m}.{y}" + (f" {clock[:5]}" if clock else "")


def fmt_npk(f) -> str:
    """Fertilizer row -> '3.5-1-0'; unknown parts show '?', nothing known gives ''."""
    parts = [f["n"], f["p"], f["k"]]
    if all(v is None for v in parts):
        return ""
    return "-".join("?" if v is None else f"{v:g}" for v in parts)


templates.env.filters["dt"] = fmt_dt
templates.env.filters["typ"] = lambda v: i18n.tr(plants.TYPEN.get(v, ""))
templates.env.filters["npk"] = fmt_npk
templates.env.globals["slots"] = config.slots
templates.env.globals["slot_names"] = config.slot_names
templates.env.globals["slot_label"] = config.slot_label
templates.env.globals.update(_=i18n.static, tr=i18n.tr, lang=lambda: i18n.lang)
templates.env.add_extension(i18n.AutoTranslate)


def nav_active(path: str) -> str:
    for page in ("cockpit", "verlauf", "auswertung", "stammdaten", "einstellungen"):
        if path == f"/{page}" or path.startswith(f"/{page}/"):
            return page
    return "start"


def render(request: Request, name: str, status_code: int = 200, **ctx):
    root = request.scope.get("root_path", "")
    ctx["root"] = root
    ctx["public"] = getattr(request.app.state, "public", False)
    ctx["active"] = nav_active(request.scope["path"][len(root):])
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def redirect(request: Request, path: str = "/"):
    return RedirectResponse(request.scope.get("root_path", "") + path, status_code=303)


def get_conn(request: Request):
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def remove_photo_files(data_dir: str, name: str) -> None:
    for n in (name, f"t_{name}"):
        try:
            os.remove(os.path.join(data_dir, "photos", os.path.basename(n)))
        except OSError:
            pass


def snapshot_before(request: Request, reason: str) -> None:
    snapshot.snapshot(request.app.state.db_path, reason)
