from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import FakeHA


def client(tmp_path):
    return TestClient(create_app(str(tmp_path), FakeHA(), run_jobs=False))


def test_healthz(tmp_path):
    r = client(tmp_path).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "box_phase": None, "climate_days": 0}


def test_ingress_prefix_in_links(tmp_path):
    r = client(tmp_path).get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert r.status_code == 200
    assert 'href="/api/hassio_ingress/abc/static/style.css"' in r.text


def test_static_served_through_ingress(tmp_path):
    c = client(tmp_path)
    assert c.get("/static/style.css").status_code == 200
    r = c.get("/static/style.css", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert r.status_code == 200 and "text/css" in r.headers["content-type"]
