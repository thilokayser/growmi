import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from . import restore, snapshot
from .web import get_conn, redirect, render
from .i18n import tr

router = APIRouter()
MAX_BYTES = 50 * 1024 * 1024


def _folders(request: Request) -> list[str]:
    return [request.app.state.options.get("backup_dir") or snapshot.DEFAULT_DIR]


def _backups(request: Request) -> list[dict]:
    out = []
    for folder in _folders(request):
        path = os.path.join(folder, snapshot.LATEST)
        if os.path.isfile(path):
            st = os.stat(path)
            out.append({"nr": len(out), "path": path, "when": datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M"),
                        "kb": st.st_size // 1024})
    return out


def _pending(request: Request) -> str:
    return os.path.join(request.app.state.data_dir, "restore-pending.json")


def _page(request: Request, status=200, error=None, **ctx):
    return render(request, "wiederherstellen.html", status, error=error, servers=_backups(request), **ctx)


@router.get("/wiederherstellen")
def page(request: Request, fertig: int = 0, fotos: int = 0, secret: int = 0):
    return _page(request, done=bool(fertig), photos=fotos, secret=bool(secret))


@router.post("/wiederherstellen/pruefen")
async def check(request: Request, quelle: str = Form(""), nr: int = Form(0), datei: UploadFile | None = File(None),
                conn=Depends(get_conn)):
    try:
        if quelle == "server":
            found = _backups(request)
            if not 0 <= nr < len(found):
                raise ValueError(tr("Auf dem Server liegt keine Sicherung"))
            with open(found[nr]["path"], encoding="utf-8") as f:
                text = f.read(MAX_BYTES + 1)
        elif quelle == "upload" and datei is not None:
            text = (await datei.read(MAX_BYTES + 1)).decode("utf-8", errors="replace")
        else:
            raise ValueError(tr("Bitte eine Quelle wählen"))
        if len(text) > MAX_BYTES:
            raise ValueError(tr("Die Datei ist zu groß"))
        parsed = restore.parse(text)
    except ValueError as e:
        return _page(request, 400, str(e))
    with open(_pending(request), "w", encoding="utf-8") as f:
        f.write(text)
    return _page(request, rows=restore.summary(conn, parsed), photos_from=quelle == "server")


@router.post("/wiederherstellen/ausfuehren")
def run(request: Request, bestaetigt: str = Form(""), conn=Depends(get_conn)):
    if bestaetigt != "on":
        return _page(request, 400, tr("Bitte bestätige, dass die aktuellen Daten ersetzt werden"))
    pending = _pending(request)
    if not os.path.isfile(pending):
        return _page(request, 400, tr("Keine geprüfte Sicherung vorhanden, bitte zuerst prüfen"))
    try:
        with open(pending, encoding="utf-8") as f:
            parsed = restore.parse(f.read())
        restore.apply(conn, request.app.state.db_path, parsed)
    except ValueError as e:
        return _page(request, 400, str(e))
    photos = sum(restore.restore_photos(os.path.join(f, "photos"), request.app.state.data_dir) for f in _folders(request))
    os.remove(pending)
    return redirect(request, f"/wiederherstellen?fertig=1&fotos={photos}&secret={int('public.secret' in parsed['kv'])}")
