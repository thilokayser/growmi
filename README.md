<p align="center"><img src="growmi/logo.png" alt="Growmi – Track. Grow. Harvest." width="250"></p>

**English** · [Deutsch](#deutsch)

# Growmi

Plant journal, history and analysis for your grow tent, as a Home Assistant add-on. It remembers what stood where, which strain, which phase, how much water and fertilizer it got, what you noticed and what came out in the end, and tells you which strain paid off.

> **Status:** used daily by its author on one tent (Home Assistant 2026.10, amd64). Other setups are untested, `aarch64` is built but unverified. No warranty, see [License](LICENSE). Issues and feedback are welcome.

## Features

- **Spots and plants** (1 to 8 spots): every plant has its own phase and dates. Strains and breeders are reusable templates, plants are autoflower or photoperiod.
- **Watering log** with fertilizer recipes per box phase and per week, price snapshots, stock, shopping list and reminders learned from your own rhythm.
- **Journal**: notes with problem tags, interventions, photos and a photo comparison per week.
- **Harvest and analysis**: yield, rating and drying per plant, then yield per strain against water, fertilizer, energy and cost.
- **Climate**: live values, daily history per phase, VPD heatmap and a weekly report.
- **Cockpit**: alarms, device state and operating hours, fan and exhaust modes, maintenance mode, tasks per phase.
- **QR tags and kiosk display** (opt-in): one quick page per pot without login, a read-only display for an old phone at the tent.
- **Settings page**: every entity, device and spot name is configurable and testable. A feature without an entity stays hidden.
- German and English UI, dark and light theme, mobile first.
- **Backup**: nightly copy with photos, and a restore page for a rebuilt Home Assistant.

## Install

1. In Home Assistant open **Settings → Add-ons → Add-on Store → ⋮ → Repositories** and add `https://github.com/thilokayser/growmi`.
2. Install **Growmi** (the first install builds the image locally and takes a few minutes), start it and enable *Show in sidebar*.
3. Open Growmi → **Settings** and assign your entities. See [docs/ha-setup.md](docs/ha-setup.md) for the helpers and the optional blueprints, and [docs/qr-tags.md](docs/qr-tags.md) for tags and the kiosk display.

## Repository layout

| Path | Content |
|---|---|
| `growmi/` | the add-on (FastAPI, SQLite, server-rendered pages), with tests |
| `blueprints/automation/growmi/` | optional Home Assistant blueprints for light, fan, exhaust, alarms |
| `docs/` | Home Assistant setup, example helper package, QR tags |
| `tools/make_qr_stl.py` | generator for 3D-printable QR tags |

## Known limitations

- The phase and mode helpers use fixed German option names (`Keimling`, `Wachstum`, `Blüte`, `Dauer an`, …). The UI shows them translated.
- The database file is still called `growlog.db` for historical reasons.
- The control blueprints are checked on paper and in CI, not yet in a second installation (see [docs/ha-setup.md](docs/ha-setup.md)).
- Growmi is a diary and an analysis tool, not a safety system. Do not rely on its alarms for equipment that can cause damage.

## Development

```sh
cd growmi
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest
```

## License

MIT, see [LICENSE](LICENSE).

---

# Deutsch

Growmi ist Pflanzentagebuch, Verlauf und Auswertung für dein Grow-Zelt als Home-Assistant-Add-on. Es merkt sich, was wo stand, welche Sorte, welche Phase, wie viel Wasser und Dünger, was dir aufgefallen ist und was am Ende herauskam, und zeigt, welche Sorte sich gelohnt hat.

> **Stand:** Der Autor nutzt es täglich an einem Zelt (Home Assistant 2026.10, amd64). Andere Setups sind ungetestet, `aarch64` wird gebaut, ist aber nicht geprüft. Keine Gewähr, siehe [Lizenz](LICENSE).

**Funktionen:** 1 bis 8 Plätze mit eigenen Pflanzenphasen, Sorten und Hersteller als Vorlagen, Gießen mit Düngerrezepten je Box-Phase und Woche, Notizen mit Problem-Tags, Fotos und Fotovergleich, Ernte und Auswertung (Ertrag je Sorte gegen Wasser, Dünger, Strom und Kosten), Klima-Verlauf mit VPD-Heatmap, Cockpit mit Alarmen, Modi und Wartungsmodus, QR-Tags und Kiosk-Anzeige (optional), Einstellungsseite für alle Entities, Deutsch und Englisch, dunkel und hell, nächtliche Sicherung mit Fotos und Wiederherstellen.

**Installieren:** In Home Assistant **Einstellungen → Add-ons → Add-on-Store → ⋮ → Repositories** und `https://github.com/thilokayser/growmi` hinzufügen, **Growmi** installieren (der erste Bau dauert ein paar Minuten), starten, „In Seitenleiste anzeigen“ einschalten. Dann in Growmi unter **Einstellungen** die Entities zuordnen. Hilfsmittel und Blueprints stehen in [docs/ha-setup.md](docs/ha-setup.md), Tags und Kiosk in [docs/qr-tags.md](docs/qr-tags.md).

**Bekannte Grenzen:** Die Helfer für Phase und Modi benutzen feste deutsche Optionsnamen (die Oberfläche zeigt sie übersetzt). Growmi ist ein Tagebuch, kein Sicherheitssystem: Verlass dich bei Geräten, die Schaden anrichten können, nicht auf seine Alarme.
