# Growmi

Growmi is the memory of your grow: which plant stood where, which strain, which phase, how much water and fertilizer it got, what you noticed, what came out in the end. It reads your tent climate from Home Assistant but never controls light, fan or exhaust by itself (the optional blueprints do that in Home Assistant).

## First start

1. Open **Growmi** in the sidebar. A fresh install is empty on purpose.
2. Open **Settings** and assign your Home Assistant entities. Each field has a pick list and a **Test** button that shows the current value. Leave a field empty and the matching feature stays hidden.
3. Add your devices (switches), choose how many spots your tent has (1 to 8) and name them.
4. Add a fertilizer under **Master data** and plant your first plant on the tent page.

The language follows Home Assistant by default. You can force German or English in **Settings → Language**.

## Entities Growmi can use

All optional. See `docs/ha-setup.md` in the repository for a ready-to-copy helper package.

| Setting | Entity type | Used for |
|---|---|---|
| Temperature, humidity, VPD | sensor | live tiles, climate history, heatmap, heat alarm |
| Sensor online | binary_sensor | cockpit alerts and the event log |
| Box phase | input_select with the options `Keimling`, `Wachstum`, `Blüte` | recipes per phase, phase suggestion |
| Light on / off | input_datetime (time only) | light cycle in the journal |
| Fan mode | input_select with `Auto`, `Dauer an`, `Dauer aus` | buttons in the cockpit |
| Exhaust mode | input_select with `Feuchteschutz`, `Standard` | buttons in the cockpit |
| Maintenance timer | timer | maintenance mode button |
| Price | input_number (€/kWh) | cost per plant |
| Energy | sensor (kWh, total increasing) | energy per plant and day |
| Devices | switch | state tiles, operating hours, wear counter |

The option names above are fixed identifiers, the app shows them translated.

## Add-on options

| Option | Default | Meaning |
|---|---|---|
| `public_port` | 8100 | port of the QR quick pages. It is also written into the QR links, so use the same number as host port under Network |
| `ha_url` | empty | address used in QR links, for example `http://homeassistant.local:8123` |
| `backup_dir` | `/share/growmi` | folder for the nightly backup |
| `energy_entity`, `notify_service`, `strompreis_eur_kwh` | empty / 0 | fallbacks if the Settings page leaves them empty |
| `weather_entity`, `weather_hot_c` | empty / 30 | heat hint for tomorrow |
| `quiet_from`, `quiet_to` | 22:00 / 07:00 | no non-critical pushes at night |
| `water_reminder_days` | 4 | fixed reminder until Growmi has learned your rhythm |

## QR tags and kiosk display (optional, off by default)

QR tags open a quick page (photo, watering, note, tasks) without a Home Assistant login. To use them, set the host port for `8100/tcp` under the add-on's **Network** section to the same number as `public_port`. The address contains a long random secret and only quick pages are reachable through it. Do not forward this port to the internet. Print tags with `tools/make_qr_stl.py` (see `docs/qr-tags.md`). `/s/<secret>/kiosk` is a read-only display for an old phone.

## Backups

Every night Growmi writes `growmi-latest.json`, database copies and your photos to the backup folder. Home Assistant backups include the add-on data as well. To restore after a rebuild, install the add-on, open **Settings → Restore backup** and choose the file. You see what will be replaced before you confirm.

## Deutsch

Growmi ist das Gedächtnis deines Grows: welche Pflanze wo stand, Sorte, Phase, Wasser und Dünger, Notizen, Ertrag. Die Klimadaten liest es aus Home Assistant, steuert aber selbst nichts (das übernehmen die optionalen Blueprints).

**Erster Start:** Growmi in der Seitenleiste öffnen, unter **Einstellungen** die Entities zuordnen (mit **Testen**), Geräte und Plätze anlegen, dann unter **Stammdaten** einen Dünger anlegen und die erste Pflanze einsetzen. Nicht zugeordnete Funktionen bleiben ausgeblendet.

**QR-Tags:** Standardmäßig aus. Zum Einschalten unter **Netzwerk** des Add-ons den Host-Port für `8100/tcp` eintragen (gleiche Zahl wie die Option `public_port`). Die Adresse enthält ein langes Zufallswort und gibt nur Schnellseiten frei. Den Port nicht ins Internet weiterleiten.

**Sicherung:** Jede Nacht liegen `growmi-latest.json`, Datenbankkopien und die Fotos im Ordner `backup_dir`. Wiederherstellen: Add-on installieren, **Einstellungen → Sicherung wiederherstellen**.
