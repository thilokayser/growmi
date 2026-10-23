import re

from app import plants
from app.routes_home import canopy_pct
from tests.test_routes_home import seed_plant


def test_canopy_grows_with_age_and_is_clamped():
    assert canopy_pct(0) == 45 and canopy_pct(-5) == 45
    assert canopy_pct(35) == 67.5
    assert canopy_pct(70) == 90 and canopy_pct(200) == 90


def cell(html: str, slot: int) -> str:
    return re.search(rf'<a class="slot[^"]*"[^>]*data-slot="{slot}".*?</a>', html, re.S).group(0)


def test_slots_are_placed_front_left_to_back_right(web):
    html = web.client.get("/").text
    expected = {1: ("vorne links", 2, 1), 2: ("vorne rechts", 2, 2), 3: ("hinten links", 1, 1),
                4: ("hinten rechts", 1, 2)}
    for slot, (pos, row, col) in expected.items():
        c = cell(html, slot)
        assert f'data-pos="{pos}"' in c, slot
        assert f"grid-row:{row};grid-column:{col}" in c, slot
        assert pos in c  # the position is also readable text, not only layout


def test_tent_map_has_front_and_back_labels(web):
    html = web.client.get("/").text
    assert "Hinten" in html and "Vorne" in html
    assert html.index("Hinten") < html.index("Vorne")


def test_plant_canopy_uses_phase_color_and_age_size(web):
    seed_plant(web, 1, phase="Blüte")
    html = web.client.get("/").text
    c = cell(html, 1)
    size = float(re.search(r"--size:([\d.]+)%", c).group(1))
    assert 'class="canopy ph-Blüte"' in c and 45 <= size <= 90
    assert 'class="canopy ph-' not in cell(html, 2)  # free spots draw no plant


def test_free_spot_links_to_planting_with_slot(web):
    html = web.client.get("/").text
    assert 'href="/pflanze/neu?slot=3"' in cell(html, 3)


def test_cell_names_plant_and_water(web):
    pid = seed_plant(web, 4, "Amnesia Haze")
    c = cell(web.client.get("/").text, 4)
    assert "Amnesia Haze" in c and f"/pflanze/{pid}" in c and "Platz 4" in c
