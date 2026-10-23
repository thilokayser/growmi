import hmac
import re
import secrets

from . import events

# what the LAN-facing app for the QR tags may serve: the quick pages and nothing that edits master data
ALLOWED = re.compile(
    r"^/(platz/\d+|kiosk|foto|fotos/[A-Za-z0-9._-]+|static/[A-Za-z0-9._/-]+|"
    r"pflanze/\d+/(schnell|schnell/giessen|notiz)|aufgabe/\d+/(erledigt|spaeter))$")


def ensure_secret(conn) -> str:
    value = events.kv_get(conn, "public.secret")
    if not value:
        value = secrets.token_urlsafe(18)
        events.kv_set(conn, "public.secret", value)
        conn.commit()
    return value


def gate(path: str, method: str, secret: str) -> str | None:
    """Returns the path without the secret prefix, or None when the request must get a plain 404."""
    parts = path.split("/", 3)  # ['', 's', '<secret>', 'rest...']
    if len(parts) < 4 or parts[1] != "s" or not hmac.compare_digest(parts[2], secret):
        return None
    rest = "/" + parts[3]
    if method not in ("GET", "HEAD", "POST") or not ALLOWED.match(rest):
        return None
    return rest
