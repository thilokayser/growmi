import sqlite3

from .plants import norm_typ
from .i18n import tr



def _clean(sorte: str, hersteller: str) -> tuple[str, str]:
    sorte, hersteller = sorte.strip(), hersteller.strip()
    if not sorte:
        raise ValueError(tr("Bitte eine Sorte angeben"))
    return sorte, hersteller


def get_strain(conn, strain_id: int):
    return conn.execute("SELECT * FROM strain WHERE id=?", (strain_id,)).fetchone()


def add_strain(conn, sorte: str, hersteller: str = "", notiz: str = "", typ: str | None = None) -> int:
    sorte, hersteller = _clean(sorte, hersteller)
    typ = norm_typ(typ)
    try:
        cur = conn.execute("INSERT INTO strain(sorte, hersteller, notiz, typ) VALUES (?,?,?,?)", (sorte, hersteller, notiz, typ))
    except sqlite3.IntegrityError:
        raise ValueError(tr("Diese Sorte gibt es mit diesem Hersteller schon")) from None
    conn.commit()
    return cur.lastrowid


def ensure_strain(conn, sorte: str, hersteller: str = "", typ: str | None = None) -> int:
    """Id of the template for this Sorte + Hersteller (case-insensitive); created if missing."""
    sorte, hersteller = _clean(sorte, hersteller)
    row = conn.execute("SELECT id FROM strain WHERE sorte=? COLLATE NOCASE AND hersteller=? COLLATE NOCASE",
                       (sorte, hersteller)).fetchone()
    return row["id"] if row else add_strain(conn, sorte, hersteller, typ=typ)


def update_strain(conn, strain_id: int, **fields) -> None:
    bad = set(fields) - {"sorte", "hersteller", "notiz", "typ"}
    if bad:
        raise ValueError(tr("Nicht änderbar: {bad}", bad=sorted(bad)))
    if "sorte" in fields and not fields["sorte"].strip():
        raise ValueError(tr("Bitte eine Sorte angeben"))
    if "typ" in fields:
        fields["typ"] = norm_typ(fields["typ"])
    fields = {k: v.strip() if k not in ("notiz", "typ") else v for k, v in fields.items()}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        try:
            conn.execute(f"UPDATE strain SET {sets} WHERE id=?", (*fields.values(), strain_id))
        except sqlite3.IntegrityError:
            raise ValueError(tr("Diese Sorte gibt es mit diesem Hersteller schon")) from None
        conn.commit()


def delete_strain(conn, strain_id: int) -> None:
    conn.execute("DELETE FROM strain WHERE id=?", (strain_id,))
    conn.commit()


def list_strains(conn) -> list:
    return conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM plant p WHERE p.sorte=s.sorte COLLATE NOCASE"
        " AND p.hersteller=s.hersteller COLLATE NOCASE) AS plant_count FROM strain s"
        " ORDER BY s.sorte COLLATE NOCASE, s.hersteller COLLATE NOCASE").fetchall()
