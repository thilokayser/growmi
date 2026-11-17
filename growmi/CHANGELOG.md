# Changelog

## 0.25.0
- Watering: enter liters and fertilizer (ml per product) for each plant instead of one amount split equally. The recipe pre-fills the ml fields (liters x ml/L) and you can overwrite them. The plant page and the analysis use each plant's own amounts, the stock count uses the sum.
- The quick page now takes liters per plant ("all plants" gives each plant that amount).
- Existing waterings keep their equal split as per-plant values.

## 0.24.1
- Heatmap: the first hour after lights-on is judged like the night, so the warm-up hour is no longer marked "too humid".

## 0.24.0
- Cockpit redesign: climate tiles (temperature, humidity, VPD with 24 h range) right under the alarms, devices in one grouped card.

## 0.23.0
- A "Mangel" or "Schädling" entry creates a check-up task five days later.
- Autoflowers get a trichome and drying-spot task on day 78.

## 0.22.1
- Display mode (kiosk) can be opened with an icon in the top right next to the theme switch, and left again from the display page.

## 0.22.0
- When the box is in Blüte but plants are still in an earlier phase, a banner offers to move the plants along (autoflowers included).
- VPD bands per phase are editable in the settings; heatmap, "VPD in target" and the cockpit use them.
- The weekly photo reminder now carries a link to each plant's quick page.

## 0.21.0 – first public release
- Plant journal for up to 8 spots: plants with their own phases, strains and breeders as templates, notes with problem tags, photos and photo comparison.
- Watering with fertilizer recipes per box phase and per week, price snapshots, stock and shopping list.
- Analysis per strain: yield against water, fertilizer, energy and cost. Climate history and heatmap, weekly report.
- Cockpit with alarms, devices, fan and exhaust modes, maintenance mode and wear counters.
- QR quick pages and a kiosk display for an old phone at the tent (opt-in LAN port, secret address).
- Settings page: all Home Assistant entities, devices and spot names are configurable and testable. Features without an entity stay hidden.
- German and English interface, dark and light theme.
- Nightly backup including photos, and a restore page.
