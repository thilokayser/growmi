import io
import re

from PIL import Image

from app import db, public, qr
from tests.test_routes_home import count, seed_plant

P = "/s/secret123"


def test_secret_is_generated_once_and_long(tmp_path):
    path = str(tmp_path / "x.db")
    c = db.connect(path)
    db.init_schema(c)
    a = public.ensure_secret(c)
    assert len(a) >= 20 and public.ensure_secret(c) == a
    c.close()


def test_slot_urls_use_the_public_port_and_secret(web):
    urls = qr.slot_urls({"ha_url": "http://192.0.2.10:8123", "public_port": 8100}, web.ha, "abc")
    assert urls[2] == "http://192.0.2.10:8100/s/abc/platz/2"


def test_qr_page_of_the_ingress_app_prints_public_urls(web):
    t = web.client.get("/qr").text
    assert re.search(r"http://[^<]+:8100/s/[A-Za-z0-9_-]{20,}/platz/1", t)


def test_wrong_or_missing_secret_is_a_plain_404(pub):
    seed_plant(pub, 1)
    for url in ("/platz/1", "/s/falsch/platz/1", "/s/secret12/platz/1", "/s//platz/1", "/"):
        assert pub.client.get(url).status_code == 404, url


def test_only_quick_pages_are_reachable(pub):
    seed_plant(pub, 1)
    for url in ("/stammdaten", "/export.json", "/auswertung", "/cockpit", "/pflanze/1", "/pflanze/neu", "/qr",
                "/giessen", "/verlauf", "/healthz"):
        assert pub.client.get(P + url).status_code == 404, url
    for url in ("/stammdaten/duenger/1/loeschen", "/pflanze/1/loeschen", "/box/phase"):
        assert pub.client.post(P + url, data={}).status_code == 404, url
    assert pub.client.delete(P + "/platz/1").status_code == 404


def test_scan_flow_works_under_the_secret_prefix(pub):
    a = seed_plant(pub, 1, "Alpha")
    r = pub.client.get(P + "/platz/1")
    assert r.status_code == 307 and r.headers["location"] == f"{P}/pflanze/{a}/schnell"
    page = pub.client.get(P + f"/pflanze/{a}/schnell").text
    assert "Alpha" in page and f'action="{P}/foto"' in page and f'action="{P}/pflanze/{a}/schnell/giessen"' in page
    assert f"{P}/static/style.css" in page and "alle Details" not in page
    assert "<nav" in page and page.count('aria-current="page"') == 1  # same tab bar look as the rest of the app
    assert f'href="{P}/platz/2"' in page and f'href="{P}/kiosk"' in page
    assert not re.search(r'href="[^"]*/(stammdaten|cockpit|verlauf|auswertung|export)', page)
    assert re.search(r'aria-current="page"[^>]*>(?:(?!</a>).)*Platz 1', page, re.S) or 'Platz 1' in page
    r = pub.client.post(P + f"/pflanze/{a}/schnell/giessen", data={"liters": "2", "rezept": "wasser", "scope": "all"})
    assert r.status_code == 303 and r.headers["location"] == f"{P}/pflanze/{a}/schnell?ok=giessen"
    assert count(pub, "watering") == 1
    assert pub.client.get(P + "/static/style.css").status_code == 200


def test_photo_and_note_and_tasks_work_publicly(pub):
    a = seed_plant(pub, 1)
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), "green").save(buf, "PNG")
    r = pub.client.post(P + "/foto", data={"plant_id": a, "back": f"/pflanze/{a}/schnell?ok=foto"},
                        files={"datei": ("a.png", buf.getvalue(), "image/png")})
    assert r.status_code == 303 and r.headers["location"] == f"{P}/pflanze/{a}/schnell?ok=foto"
    assert pub.client.post(P + f"/pflanze/{a}/notiz", data={"text": "ok"}).status_code == 303
    name = [r[0] for r in pub.conn().execute("SELECT filename FROM photo")][0]
    assert pub.client.get(P + f"/fotos/t_{name}").status_code == 200
    assert pub.client.get(P + "/fotos/..%2Fgrowlog.db").status_code == 404


def test_empty_slot_shows_a_hint_instead_of_a_blocked_form(pub):
    r = pub.client.get(P + "/platz/3")
    assert r.status_code == 200 and "frei" in r.text and "pflanze/neu" not in r.text


def test_kiosk_is_readable_publicly(pub):
    r = pub.client.get(P + "/kiosk")
    assert r.status_code == 200 and "<nav" not in r.text


def test_public_tab_bar_marks_the_current_slot(pub):
    seed_plant(pub, 1, "Alpha")
    seed_plant(pub, 2, "Beta")
    c = pub.conn()
    pid = c.execute("SELECT id FROM plant WHERE slot=2").fetchone()[0]
    c.close()
    page = pub.client.get(P + f"/pflanze/{pid}/schnell").text
    current = re.search(r'<a href="[^"]*"\s*aria-current="page">(.*?)</a>', page, re.S).group(1)
    assert "Platz 2" in current
    free = pub.client.get(P + "/platz/4").text
    assert "Platz 4" in re.search(r'aria-current="page">(.*?)</a>', free, re.S).group(1)
