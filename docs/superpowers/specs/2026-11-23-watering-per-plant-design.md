# Watering per plant from the overview, bulk watering as its own page

## Intent
Watering is a per-plant act. Today the home page has one Gießen button that opens a table for all plants. The author wants to water one plant straight from the overview, and keep a separate "water all" function for the times the whole tent gets the same.

## Goals
- Every plant card on the home page has a water-drop button; one tap opens a sheet to water that plant only.
- Bulk watering becomes its own function on `/giessen` ("Alle gießen").
- QR quick page waters only its plant.

## Non-goals / anti-goals
- No schema change, no change to analysis, stock or editing of old entries (0.26.0 stays).
- Per-plant watering must not become slower than today (one tap + one confirm at most).

## Approaches considered
1. Drop button + sheet on the card (chosen): amount and recipe visible and editable, no layout growth.
2. One-tap with last amount: fastest, hard to change amount. Rejected.
3. Inline fields on every card: cards grow, cluttered. Rejected.

## Design
- Card: second element next to the link (not nested in it) with a drop button. Sheet fields: litres (default = this plant's last amount), recipe (default plan, else box phase), computed ml preview, optional pH/EC. Posts to `POST /pflanze/{id}/giessen` using `add_watering` with one plant. Without JS the button links to `GET /pflanze/{id}/giessen` (same form).
- After saving: redirect home with a status line "Gegossen · Rückgängig"; undo deletes exactly that watering entry.
- Card text: "gestern, 1,5 L" (last amount). Thirst hint: highlight card and drop button when days since water exceed the plant's learned rhythm (reuse the reminder logic in `calc`/`stock`/`tasks`).
- Bulk `/giessen`: plant checkboxes (all occupied plants ticked except those watered today), one litres value and one recipe for all, pH/EC, time; each plant expandable for own litres/ml; former plants stay under "Weitere Pflanzen". Home action button reads "Alle gießen".
- QR quick page: remove the `scope` radio; water route takes only the one plant.
- i18n: all new strings through `tr`, English entries added; page/a11y tests updated.

## Left to the builder
Exact sheet markup (`<dialog>` preferred), thirst threshold fallback when no rhythm exists yet, wording.
