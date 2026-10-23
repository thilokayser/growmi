# Home Assistant setup

Growmi works without any of this: an empty Settings page gives you the plant journal, watering log and analysis. Everything below is optional and adds climate data, controls and alarms.

## What Growmi reads and writes in Home Assistant

| Direction | What |
|---|---|
| reads | the sensors, switches and helpers you assign under **Settings** (states and history) |
| writes | five summary sensors, see below |
| writes (only when you press a button) | the box phase and fan/exhaust mode helpers (`input_select.select_option`), the maintenance timer (`timer.start` / `timer.cancel`), the light preset script (phase link) |
| notifies | a persistent notification and the notification service you set (water, photo and task reminders, weekly report, weather hint) |

Growmi never switches your light, fan or exhaust by itself. Use the blueprints below for that.

### Sensors Growmi publishes

| Entity | Meaning |
|---|---|
| `sensor.growmi_pflanzen` | plants in the tent, with the number per phase as attributes (`keimling`, `wachstum`, `bluete`, `trocknung`) |
| `sensor.growmi_tage_seit_giessen` | days since the last watering |
| `sensor.growmi_grow_woche` | week of the oldest plant (attribute `tage` has the days) |
| `sensor.growmi_kosten` | grow costs so far in € |
| `sensor.growmi_aufgaben` | open tasks due today |

They are republished every minute. They are virtual states, so they disappear when Home Assistant restarts and come back within a minute after Growmi started.

## Helper package

[`ha-helpers.example.yaml`](ha-helpers.example.yaml) defines the helpers the settings page and the blueprints expect: box phase, fan and exhaust mode, light and fan times, electricity price, maintenance timer, VPD, VPD target and a "climate sensor online" sensor, plus the light preset script. Copy it to `<config>/packages/growmi.yaml`, replace the three `REPLACE` placeholders with your own entities and restart. You can also create the same helpers in the UI.

Fixed names: the box phase needs the options `Keimling`, `Wachstum`, `Blüte`. The fan mode needs `Auto`, `Dauer an`, `Dauer aus`. The exhaust mode needs `Feuchteschutz`, `Standard`. Growmi shows them translated, but compares and writes these exact strings.

## Blueprints

Copy the files from [`blueprints/automation/growmi`](../blueprints/automation/growmi) to `<config>/blueprints/automation/growmi/`, then create automations under **Settings → Automations → Create → Use blueprint**.

| Blueprint | Does |
|---|---|
| Light schedule | light on/off from two time helpers, also after a restart |
| Fan control | fan by times plus heat rule, modes Auto / Dauer an / Dauer aus |
| Exhaust by VPD | exhaust against a VPD target with dead band and humidity protection |
| Airing burst | hourly fresh air when the exhaust stayed off for long |
| Maintenance mode | pauses the listed automations and switches while a timer runs |
| Climate alarm | notification for heat and VPD that stays out of range |
| Light alarm | lamp on but (almost) no power drawn |
| Climate sensor alarm | silent, missing or low-battery climate sensor |
| Add-on watchdog | Growmi stopped reporting |
| Kiosk phone charge guard | keeps the phone battery between two limits via a smart plug |

The control blueprints (light, fan, exhaust, airing burst) are generalizations of the author's own automations. Their decision logic was checked against the originals on 1232 input combinations, and the files are structure-checked in CI. They have **not** yet been imported into a second Home Assistant installation, so please test them with the device you can reach by hand first, and open an issue if something is off.

## Dashboard

Growmi is a sidebar panel. For the Home Assistant dashboard, the five sensors above work in any entities or tile card, and a tile card with `navigate` to `/local_growmi` opens the app (the exact path is shown in the add-on's panel URL).
