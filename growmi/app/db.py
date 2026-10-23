import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS plant(
  id INTEGER PRIMARY KEY, sorte TEXT NOT NULL, hersteller TEXT NOT NULL DEFAULT '',
  keimdatum TEXT, topf TEXT NOT NULL DEFAULT '', notiz TEXT NOT NULL DEFAULT '',
  slot INTEGER NOT NULL, eingesetzt_am TEXT NOT NULL, ausgezogen_am TEXT,
  trocken_g REAL, nass_g REAL);
CREATE TABLE IF NOT EXISTS plant_phase(
  id INTEGER PRIMARY KEY, plant_id INTEGER NOT NULL REFERENCES plant(id) ON DELETE CASCADE,
  phase TEXT NOT NULL, ab TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fertilizer(
  id INTEGER PRIMARY KEY, produkt TEXT NOT NULL, hersteller TEXT NOT NULL DEFAULT '',
  n REAL, p REAL, k REAL, filename TEXT);
CREATE TABLE IF NOT EXISTS recipe_item(
  box_phase TEXT NOT NULL, fertilizer_id INTEGER NOT NULL REFERENCES fertilizer(id) ON DELETE CASCADE,
  ml_per_l REAL NOT NULL);
CREATE TABLE IF NOT EXISTS watering(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, liters REAL NOT NULL, ph REAL, ec REAL);
CREATE TABLE IF NOT EXISTS watering_plant(
  watering_id INTEGER NOT NULL REFERENCES watering(id) ON DELETE CASCADE,
  plant_id INTEGER NOT NULL REFERENCES plant(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS watering_item(
  id INTEGER PRIMARY KEY, watering_id INTEGER NOT NULL REFERENCES watering(id) ON DELETE CASCADE,
  produkt TEXT NOT NULL, hersteller TEXT NOT NULL DEFAULT '', ml_per_l REAL NOT NULL, ml_total REAL NOT NULL);
CREATE TABLE IF NOT EXISTS intervention(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, plant_id INTEGER NOT NULL REFERENCES plant(id) ON DELETE CASCADE,
  art TEXT NOT NULL, text TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS photo(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, plant_id INTEGER NOT NULL REFERENCES plant(id) ON DELETE CASCADE,
  filename TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS box_phase_change(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, phase TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS strain(
  id INTEGER PRIMARY KEY, sorte TEXT NOT NULL, hersteller TEXT NOT NULL DEFAULT '', notiz TEXT NOT NULL DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS strain_uq ON strain(sorte COLLATE NOCASE, hersteller COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS box_event(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS task(
  id INTEGER PRIMARY KEY, plant_id INTEGER NOT NULL REFERENCES plant(id) ON DELETE CASCADE, key TEXT NOT NULL,
  title TEXT NOT NULL, due TEXT NOT NULL, done_at TEXT, UNIQUE(plant_id, key));
CREATE TABLE IF NOT EXISTS recipe_week(
  box_phase TEXT NOT NULL, week INTEGER NOT NULL, fertilizer_id INTEGER NOT NULL REFERENCES fertilizer(id) ON DELETE CASCADE,
  ml_per_l REAL NOT NULL);
CREATE TABLE IF NOT EXISTS recipe_week_flag(
  box_phase TEXT NOT NULL, week INTEGER NOT NULL, water_only INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(box_phase, week));
CREATE TABLE IF NOT EXISTS device_day(
  day TEXT NOT NULL, device TEXT NOT NULL, hours REAL NOT NULL, PRIMARY KEY(day, device));
CREATE TABLE IF NOT EXISTS wear(
  device TEXT PRIMARY KEY, limit_h REAL, reset_day TEXT);
CREATE TABLE IF NOT EXISTS climate_hour(
  day TEXT NOT NULL, hour INTEGER NOT NULL, vpd REAL, temp REAL, rh REAL, light INTEGER, phase TEXT, PRIMARY KEY(day, hour));
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS climate_day(
  day TEXT PRIMARY KEY, t_min REAL, t_max REAL, t_avg REAL, rh_avg REAL, vpd_avg REAL,
  light_h REAL, box_phase TEXT);
"""


# columns added after the first release; init_schema adds them to databases created earlier
ADDED_COLUMNS = [("fertilizer", "n", "REAL"), ("fertilizer", "p", "REAL"), ("fertilizer", "k", "REAL"),
                 ("fertilizer", "filename", "TEXT"), ("fertilizer", "preis_eur", "REAL"),
                 ("fertilizer", "flasche_ml", "REAL"), ("watering_item", "eur_per_ml", "REAL"),
                 ("plant", "bew_geschmack", "INTEGER"), ("plant", "bew_wirkung", "INTEGER"),
                 ("plant", "bew_aufwand", "INTEGER"), ("plant", "trocknung_tage", "INTEGER"),
                 ("plant", "ernte_notiz", "TEXT"), ("climate_day", "vpd_ok_pct", "REAL"),
                 ("climate_day", "kwh", "REAL"), ("plant", "typ", "TEXT"), ("strain", "typ", "TEXT"),
                 ("fertilizer", "bestand_ml", "REAL"), ("fertilizer", "bestand_ab", "TEXT"),
                 ("intervention", "tag", "TEXT")]


def connect(path: str) -> sqlite3.Connection:
    # one connection per request, used by one task at a time; async routes hop threads
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    had_strains = conn.execute("SELECT 1 FROM sqlite_master WHERE name='strain'").fetchone() is not None
    conn.executescript(SCHEMA)
    if not had_strains:  # first start with the strain library: seed it from the plants already there
        conn.execute("INSERT OR IGNORE INTO strain(sorte, hersteller) SELECT sorte, hersteller FROM plant"
                     " WHERE trim(sorte) != '' ORDER BY id")
    for table, column, kind in ADDED_COLUMNS:
        if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    # kWh used to be max-min of the meter, which a meter reset inflated: recompute the days the recorder still has
    try:  # height measurements were removed again; drop the table only if nobody entered anything
        if conn.execute("SELECT COUNT(*) FROM measure").fetchone()[0] == 0:
            conn.execute("DROP TABLE measure")
    except sqlite3.OperationalError:
        pass
    if conn.execute("SELECT 1 FROM kv WHERE k='fix.kwh.reset'").fetchone() is None:
        conn.execute("DELETE FROM climate_day WHERE kwh IS NOT NULL AND day >= date('now', '-9 day')")
        conn.execute("INSERT INTO kv(k, v) VALUES ('fix.kwh.reset', '1')")
    conn.commit()
