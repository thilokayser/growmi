import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, i18n, jobs, public, routes_home, routes_plants, routes_verlauf, routes_auswertung, routes_fertilizer, routes_strains, routes_export, routes_cockpit, routes_extra, routes_quick, routes_batch3, routes_restore, routes_settings
from .ha import HAClient

HERE = Path(__file__).parent


def create_app(data_dir: str, ha, run_jobs: bool = True, options: dict | None = None,
               public_secret: str | None = None) -> FastAPI:
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "growlog.db")
    boot = db.connect(db_path)
    db.init_schema(boot)
    secret = public_secret or public.ensure_secret(boot)
    config.load(boot)
    i18n.set_lang(config.current["lang"], ha.language())
    boot.close()

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(jobs.run_loop(db_path, ha, options=options)) if run_jobs else None
        server = serve = None
        port = int((options or {}).get("public_port", 8100) or 0)
        if run_jobs and port and not public_secret:  # LAN-facing twin of this app for the QR tags
            import uvicorn
            twin = create_app(data_dir, ha, run_jobs=False, options=options, public_secret=secret)
            server = uvicorn.Server(uvicorn.Config(twin, host="0.0.0.0", port=port, log_level="warning"))
            serve = asyncio.create_task(server.serve())
        yield
        if task:
            task.cancel()
        if server:
            server.should_exit = True
            await serve

    app = FastAPI(lifespan=lifespan)
    app.state.db_path = db_path
    app.state.data_dir = data_dir
    app.state.ha = ha
    app.state.options = options or {}
    app.state.public = bool(public_secret)
    app.state.public_secret = secret
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    if public_secret:
        @app.middleware("http")
        async def secret_gate(request: Request, call_next):
            rest = public.gate(request.scope["path"], request.method, public_secret)
            if rest is None:
                return PlainTextResponse("Not Found", status_code=404)
            request.scope["root_path"] = f"/s/{public_secret}"  # path keeps the prefix, as Starlette expects
            return await call_next(request)
    else:
        @app.middleware("http")
        async def ingress_prefix(request: Request, call_next):
            # HA ingress strips the prefix from the path and passes it in this header
            root = request.headers.get("X-Ingress-Path", "")
            request.scope["root_path"] = root
            # Starlette (Mount/StaticFiles) expects root_path to be part of path, ingress sends it stripped
            request.scope["path"] = root + request.scope["path"]
            return await call_next(request)

    @app.get("/healthz")
    def healthz():  # not reachable through the public twin, the gate only lets quick pages through
        conn = db.connect(db_path)
        try:
            days = conn.execute("SELECT COUNT(*) FROM climate_day").fetchone()[0]
            return {"ok": True, "box_phase": jobs.last_box_phase(conn), "climate_days": days}
        finally:
            conn.close()

    app.include_router(routes_home.router)
    app.include_router(routes_plants.router)
    app.include_router(routes_verlauf.router)
    app.include_router(routes_auswertung.router)
    app.include_router(routes_fertilizer.router)
    app.include_router(routes_strains.router)
    app.include_router(routes_export.router)
    app.include_router(routes_cockpit.router)
    app.include_router(routes_extra.router)
    app.include_router(routes_quick.router)
    app.include_router(routes_batch3.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_restore.router)
    return app


def build_app() -> FastAPI:
    data = os.environ.get("GROWLOG_DATA", "/data")
    try:  # the Supervisor writes the add-on options here
        with open(os.path.join(data, "options.json")) as f:
            options = json.load(f)
    except (OSError, ValueError):
        options = {}
    return create_app(data, HAClient.from_env(), options=options)
