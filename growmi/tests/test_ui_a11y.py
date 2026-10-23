import io
import os
import re
from pathlib import Path

from PIL import Image

from app import entries, plants, watering
from app.web import nav_active
from tests.test_routes_home import seed_plant

CSS = Path(__file__).parent.parent / "app" / "static" / "style.css"
EMOJI = "💧📝📷🗑✏️✂️🪢🪴🐛"


def test_nav_active():
    assert nav_active("/") == "start" and nav_active("/pflanze/3") == "start"
    assert nav_active("/verlauf") == "verlauf" and nav_active("/cockpit") == "cockpit"
    assert nav_active("/auswertung") == "auswertung"
    assert nav_active("/stammdaten") == "stammdaten"


def seeded(web):
    pid = seed_plant(web, 1)
    c = web.conn()
    wid = watering.add_watering(c, ts="2026-10-20T12:00", liters=2.0, items=[], plant_ids=[pid])
    f = watering.add_fertilizer(c, "Bloom", "BioBizz")
    c.close()
    return pid, wid, f


def test_pages_have_unique_title_single_h1_and_current_nav(web):
    pid, wid, _ = seeded(web)
    urls = ["/", "/verlauf", "/auswertung", "/stammdaten", "/giessen", "/notiz", "/foto", "/pflanze/neu",
            f"/pflanze/{pid}", f"/eintrag/watering/{wid}"]
    titles = []
    for u in urls:
        t = web.client.get(u).text
        assert t.count("<h1") == 1, u
        assert t.count('aria-current="page"') == 1, u
        titles.append(re.search(r"<title>(.*?)</title>", t, re.S).group(1).strip())
    assert len(set(titles)) == len(titles)


def test_icon_buttons_have_accessible_names(web):
    pid, wid, f = seeded(web)
    t = web.client.get(f"/pflanze/{pid}").text
    for label in ("Eintrag bearbeiten", "Eintrag löschen", "Phase löschen"):
        assert f'aria-label="{label}"' in t
    assert 'aria-label="Dünger löschen"' in web.client.get("/stammdaten").text


def test_error_has_role_alert(web):
    seed_plant(web, 1)
    r = web.client.post("/giessen", data={"liters": "0", "rezept": "wasser"})
    assert 'role="alert"' in r.text


def test_required_fields_marked(web):
    t = web.client.get("/giessen").text
    assert 'class="req"' in t


def test_no_emoji_icons_in_pages(web):
    pid, wid, _ = seeded(web)
    c = web.conn()
    entries.add_intervention(c, ts="2026-10-21T09:00", plant_id=pid, art="Topping")
    c.close()
    for u in ("/", f"/pflanze/{pid}", "/verlauf?von=2026-09-01&bis=2026-10-31", "/stammdaten", "/giessen"):
        t = web.client.get(u).text
        assert not [ch for ch in EMOJI if ch in t], u


def test_auswertung_cells_have_data_labels(web):
    seed_plant(web, 1)
    t = web.client.get("/auswertung").text
    for label in ("Ertrag trocken", "Wasser", "Dünger", "g pro L", "g pro ml"):
        assert f'data-label="{label}"' in t


def upload(web, pid):
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), "green").save(buf, "PNG")
    web.client.post("/foto", data={"plant_id": pid, "ts": "2026-10-20T09:00"},
                    files={"datei": ("a.png", buf.getvalue(), "image/png")})
    c = web.conn()
    row = c.execute("SELECT id, filename FROM photo").fetchone()
    c.close()
    return row["id"], row["filename"]


def test_photo_thumbnail_created_served_lazy_and_removed(web):
    pid = seed_plant(web, 1)
    photo_id, name = upload(web, pid)
    folder = os.path.join(web.data_dir, "photos")
    assert max(Image.open(os.path.join(folder, f"t_{name}")).size) == 320
    page = web.client.get(f"/pflanze/{pid}").text
    assert f"/fotos/t_{name}" in page and 'loading="lazy"' in page
    assert web.client.get(f"/fotos/t_{name}").status_code == 200
    os.remove(os.path.join(folder, f"t_{name}"))
    assert web.client.get(f"/fotos/t_{name}").status_code == 200  # falls back to the original
    web.client.post(f"/eintrag/photo/{photo_id}/loeschen")
    assert os.listdir(folder) == []


def parse_tokens(block: str) -> dict:
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def themes():
    css = CSS.read_text()
    light_at = css.index("prefers-color-scheme: light")
    dark = parse_tokens(css[:light_at])
    light = {**dark, **parse_tokens(css[light_at:])}
    return {"mocha": dark, "latte": light}


def test_css_only_uses_catppuccin_palette():
    palette = set("""f5e0dc f2cdcd f5c2e7 cba6f7 f38ba8 eba0ac fab387 f9e2af a6e3a1 94e2d5 89dceb 74c7ec 89b4fa b4befe
        cdd6f4 bac2de a6adc8 9399b2 7f849c 6c7086 585b70 45475a 313244 1e1e2e 181825 11111b
        dc8a78 dd7878 ea76cb 8839ef d20f39 e64553 fe640b df8e1d 40a02b 179299 04a5e5 209fb5 1e66f5 7287fd
        4c4f69 5c5f77 6c6f85 7c7f93 8c8fa1 9ca0b0 acb0be bcc0cc ccd0da eff1f5 e6e9ef dce0e8""".split())
    used = {h.lower() for h in re.findall(r"#([0-9a-fA-F]{6})\b", CSS.read_text())}
    assert used <= palette, used - palette


def test_theme_contrast_meets_wcag():
    pairs = [("text", "bg", 4.5), ("text", "card", 4.5), ("muted", "bg", 4.5), ("muted", "card", 4.5),
             ("link", "bg", 4.5), ("on-accent", "accent", 4.5), ("on-danger", "danger", 4.5),
             ("border", "bg", 3), ("border", "card", 3), ("focus", "bg", 3), ("focus", "card", 3)]
    pairs += [(f"on-{p}", f"ph-{p}", 4.5) for p in ("keimling", "wachstum", "bluete", "trocknung", "geerntet")]
    for name, t in themes().items():
        for fg, bg, need in pairs:
            assert ratio(t[fg], t[bg]) >= need, (name, fg, bg, round(ratio(t[fg], t[bg]), 2))


def test_dt_filter_formats_german_dates(web):
    from app.web import fmt_dt
    assert fmt_dt("2026-08-22T08:00") == "22.08.2026 08:00"
    assert fmt_dt("2026-08-22") == "22.08.2026"
    assert fmt_dt(None) == "–" and fmt_dt("") == "–"
    pid = seed_plant(web, 1)
    t = web.client.get(f"/pflanze/{pid}").text
    assert "01.09.2026 08:00" in t and ">2026-09-01T08:00<" not in t


def test_home_shows_live_climate_tiles(web):
    web.ha.states.update({"input_select.grow_phase": "Wachstum", "sensor.growbox_temperatur": "22.84",
                          "sensor.growbox_luftfeuchtigkeit": "66.0", "sensor.growbox_vpd": "0.94"})
    t = web.client.get("/").text
    assert 'class="tiles"' in t and "22.8" in t and "66" in t and "0.94" in t and "im Ziel" in t
    assert "Wachstum" in t
    web.ha.states["sensor.growbox_vpd"] = "1.9"
    assert "außerhalb" in web.client.get("/").text


def test_home_tiles_survive_missing_ha_values(web):
    t = web.client.get("/").text
    assert 'class="tiles"' in t and t.count("–") >= 3


def test_app_shell_has_brand_and_icon_nav(web):
    t = web.client.get("/verlauf").text
    assert 'class="appbar"' in t and 'class="brand"' in t
    assert t.count('data-icon="') >= 5  # brand + four tabs


def test_theme_switch_is_in_the_shell_and_css_supports_forced_themes(web):
    t = web.client.get("/").text
    assert "data-theme-toggle" in t and 'localStorage.getItem("growlog-theme")' in t
    assert t.index("growlog-theme") < t.index("style.css")  # applied before the stylesheet: no flash
    css = CSS.read_text()
    assert ':root:not([data-theme])' in css and ':root[data-theme="light"]' in css
    # forcing dark on a light system must not be overridden by the media query
    assert css.index("prefers-color-scheme: light") < css.index(':root[data-theme="light"]')
    assert "growlog-theme" in web.client.get("/kiosk").text
