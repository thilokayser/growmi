import re

import pytest

from app import config, i18n
from app.i18n_en import EN
from tests import i18n_ids
from tests.pages import paths, populate

IDS = i18n_ids.collect()
# HA option names and the like that stay German on purpose, quoted in help texts
KEEP = ("Keimling, Wachstum and Blüte", "Dauer an, Dauer aus", "Selection list with Auto, Dauer an, Dauer aus.", "Selection list with Feuchteschutz, Standard.", "Deutsch")
GERMAN = re.compile(r"[äöüßÄÖÜ]|\b(nicht|und|der|die|das|noch|keine?|Platz|Pflanze|Pflanzen|Tagen|gegossen|für|wird|Zelt|Gießen|"
                    r"Dünger|Sorte|Hersteller|Eintrag|Bitte|Fehler|Woche|Tage|Wasser|Speichern|Löschen|Notiz)\b")


def fields(text: str) -> list[str]:
    return sorted(re.findall(r"\{([A-Za-z0-9_]*)", text))


def test_every_text_has_an_english_version():
    assert sorted(IDS - set(EN)) == []


def test_catalog_has_no_stale_entries():
    assert sorted(set(EN) - IDS) == []


def test_placeholders_match_between_languages():
    assert [k for k, v in EN.items() if fields(k) != fields(v)] == []


def test_no_straight_double_quotes_in_english():
    assert [k for k, v in EN.items() if '"' in v] == []


def test_tr_formats_and_falls_back():
    i18n.set_lang("en")
    assert i18n.tr("Platz {slot} ist belegt", slot=2) == "Spot 2 is occupied"
    assert i18n.tr("Ein ganz neuer Satz") == "Ein ganz neuer Satz"
    i18n.set_lang("de")
    assert i18n.tr("Platz {slot} ist belegt", slot=2) == "Platz 2 ist belegt"


@pytest.mark.parametrize("setting, ha, expected", [("de", "en", "de"), ("en", "de", "en"), ("", "de", "de"), ("", "de-DE", "de"),
                                                   ("", "en", "en"), ("", "fr", "en"), ("", None, "en"), ("xx", "de", "de")])
def test_language_resolution(setting, ha, expected):
    assert i18n.set_lang(setting, ha) == expected


def test_template_escapes_values_but_not_its_own_markup():
    i18n.set_lang("en")
    out = i18n.static("Foto von {0}", "<b>x</b>")
    assert "&lt;b&gt;" in out and "<b>" not in out
    assert str(i18n.static("a &middot; b")) == "a &middot; b"


def visible_text(html: str) -> list[str]:
    html = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S)
    nodes = re.findall(r">([^<>]+)<", html) + re.findall(r'(?:aria-label|placeholder|title|alt)="([^"]*)"', html) \
        + re.findall(r"onsubmit='([^']*)'", html)
    return [re.sub(r"\s+", " ", n).strip() for n in nodes if re.search(r"[A-Za-zÄÖÜäöüß]{2,}", n)]


def test_english_pages_contain_no_german(web):
    ids = populate(web)
    web.conn().execute("DELETE FROM box_event")  # stored in the language they were created in
    web.conn().commit()
    config.save(web.conn(), {**config.EXAMPLE, "lang": "en"})
    i18n.set_lang("en")
    problems = []
    for path in paths(ids):
        html = web.client.get(path, follow_redirects=True).text
        assert '<html lang="en">' in html, path
        for text in visible_text(html):
            for keep in KEEP:
                text = text.replace(keep, "")
            if text in IDS and EN.get(text, text) != text or GERMAN.search(text):
                problems.append((path, text))
    assert problems == []


def test_language_can_be_switched_in_settings(web):
    from tests.test_settings_page import form
    assert "Einstellungen" in web.client.get("/einstellungen").text
    assert web.client.post("/einstellungen", data=form(lang="en")).status_code == 303
    page = web.client.get("/einstellungen").text
    assert "Settings" in page and i18n.lang == "en"
    assert web.client.post("/einstellungen", data=form(lang="de")).status_code == 303
    assert i18n.lang == "de"


def test_form_values_stay_german_in_english(web):
    config.save(web.conn(), {**config.EXAMPLE, "lang": "en"})
    i18n.set_lang("en")
    html = web.client.get("/pflanze/neu").text
    assert '<option value="Blüte"' in html and ">Flowering<" in html


def test_stored_task_titles_follow_the_language(web):
    ids = populate(web)
    config.save(web.conn(), {**config.EXAMPLE, "lang": "en"})
    i18n.set_lang("en")
    html = web.client.get("/cockpit").text
    assert "Check topping/LST" in html or "Check harvest readiness" in html or "Check start of flowering" in html


def _assert_english(html: str, where: str):
    problems = []
    for text in visible_text(html):
        for keep in KEEP:
            text = text.replace(keep, "")
        if text in IDS and EN.get(text, text) != text or GERMAN.search(text):
            problems.append((where, text))
    assert problems == []


def test_english_error_and_detail_pages_contain_no_german(web):
    from app import plants
    ids = populate(web)
    c = web.conn()
    plants.add_plant(c, sorte="Delta", hersteller="", keimdatum="2026-09-01", slot=4, phase="Blüte", typ="photo")
    c.execute("DELETE FROM box_event")
    c.commit()
    config.save(c, {**config.EXAMPLE, "lang": "en"})
    i18n.set_lang("en")
    for path in ("/", "/cockpit", "/eintrag/watering/1", "/eintrag/intervention/1", "/eintrag/photo/1", "/probleme?tag=Stress",
                 "/stammdaten/sorte/1", "/pflanze/neu?slot=4", "/verlauf?tage=30"):
        r = web.client.get(path, follow_redirects=True)
        if r.status_code == 200:
            _assert_english(r.text, path)
    assert "Delta" in web.client.get("/").text and "Check" not in "" and 'class="banner"' in web.client.get("/").text
    for path, data in (("/giessen", {"liters": "abc"}), ("/pflanze/neu", {"sorte": ""}), ("/notiz", {"text": ""}),
                       ("/einstellungen", {"temp": "kaputt", "lang": "en"}), ("/wiederherstellen/ausfuehren", {}),
                       ("/wiederherstellen/pruefen", {"quelle": "server"}), ("/stammdaten/duenger", {"produkt": ""}),
                       ("/cockpit/ventilator", {"modus": "x"}), ("/aufgabe", {"titel": ""})):
        r = web.client.post(path, data=data)
        if r.status_code in (200, 400, 502):
            _assert_english(r.text, path)


def test_english_public_pages_contain_no_german(pub):
    config.save(pub.conn(), {**config.EXAMPLE, "lang": "en"})
    i18n.set_lang("en")
    for path in ("/platz/1", "/kiosk"):
        _assert_english(pub.client.get("/s/secret123" + path, follow_redirects=True).text, path)
