# Changelog

## 0.29.0
- Jar labels (Master data → Glas-Etiketten, or the button on a harvested plant): strain, breeder and a small QR code per label. A4 sheet (60 × 30 mm) or label printer (62 × 29 mm). The strain name shrinks until it fits, it is never cut.
- The QR code opens a read-only profile of the plant (harvest date, dry yield, rating, latest photo) on the LAN port, without login.

## 0.28.11
- Mobile: analysis filters and view controls no longer overlap the bottom navigation.
- Tent overview: see due tasks and alerts first, then plants and climate details. The summary links directly to the cockpit.

## 0.28.10
- Desktop: the content is centred in the space right of the sidebar instead of sticking to its edge.

## 0.28.9
- Verlauf timeline: tap or click a marker (drop, note, …) to see what happened and on which day. Clustered markers list up to five entries.

## 0.28.8
- Analysis: add photos to any plant, also harvested ones.
- Analysis: filter Alle / Fertig / Im Wachstum, and a Postkarten view (photo, name, dry yield, water) next to the table.

## 0.28.7
- Photo upload: the time the photo was taken (EXIF) is used as the entry time. Without EXIF time the form time (now) is used.

## 0.28.6
- Desktop: the navigation is a sidebar on the left (from 60 rem width). On the settings page the sidebar also lists the sections as links.
- Verlauf: the section "Ereignisse im Zelt" can be collapsed.

## 0.28.5
- Auswertung: the latest photo of each plant is the first column.
- Optional plant nicknames (off by default, switch in Einstellungen → Spitznamen). When on, the nickname replaces the strain name on the overview, plant page, timeline and analysis; the strain stays next to it. The plant form suggests rapper and stoner-meme names.

## 0.28.4
- 24 h charts on the overview show typical target bands per box phase: temperature (Keimling 22–26, Wachstum 22–28, Blüte 20–26 °C), humidity (65–75, 50–70, 40–50 %) and VPD (as before). The humidity chart is shown again next to temperature.

## 0.28.3
- The 24 h VPD chart on the overview shows the target band of the current box phase as a shaded strip, so you see at a glance whether the values stay in the band.

## 0.28.2
- Fix: the phase colors of the timeline were gone (a class name clash with the new climate gauges).

## 0.28.1
- Overview follows the dashboard look: steel-blue to slate background, lighter cards, no bar under the app bar. Climate values sit in one card with an icon badge, status pill and bars; quick actions are pills.

## 0.28.0
- New look for the whole app: deep navy background with soft color glows, rounder glass-like cards, bigger headings, pastel pill buttons and round icon badges on the live tiles of the overview. Light theme follows the same style.

## 0.27.0
- Water a single plant straight from the overview: a drop button on every plant card opens a sheet with liters (the plant's last amount), recipe with the resulting ml, and optional pH/EC. A short "Undo" appears after saving.
- The plant card shows the last amount ("yesterday · 1.5 L") and highlights plants that are overdue by your own watering rhythm.
- The top button is now "Water all": tick the plants, one amount and one recipe for all, an own amount per plant if needed. Plants already watered today start unticked. The recipe's ml are computed on the server.
- The QR quick page waters only its plant.

## 0.26.0
- Editing a watering changes liters and fertilizer per plant (prices recorded then stay).
- One field fills the liters of all plants at once.
- Fertilizer stock shows the use per week and how many days the rest lasts.
- The analysis and planning tables are fully translated; the plant card on the home page rounds the water amount.

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
