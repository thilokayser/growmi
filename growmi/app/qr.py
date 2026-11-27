from urllib.parse import urlparse

import segno

from . import config

DEFAULT_URL = "http://homeassistant.local:8123"


def _base(options: dict, ha, secret: str | None) -> str:
    base = (options.get("ha_url") or ha.config_url() or DEFAULT_URL).rstrip("/")
    if secret:  # direct LAN address with a secret instead of the ingress path (ingress refuses plain browsers with 401)
        host = urlparse(base).hostname or "homeassistant.local"
        port = int(options.get("public_port", 8100) or 8100)
        return f"http://{host}:{port}/s/{secret}"
    return f"{base}{ha.ingress_entry()}"


def slot_urls(options: dict, ha, secret: str | None = None) -> dict[int, str]:
    base = _base(options, ha, secret)
    return {slot: f"{base}/platz/{slot}" for slot in config.slots()}


def plant_url(options: dict, ha, secret: str | None, plant_id: int) -> str:
    """Target of a jar label: the read-only profile of the plant. Short path, so the code stays coarse and scans well."""
    return f"{_base(options, ha, secret)}/p/{plant_id}"


def qr_svg(url: str) -> str:
    return segno.make(url, error="m").svg_inline(scale=5, border=2, dark="#000000", light="#ffffff")


def label_svg(url: str) -> str:
    """Scales with CSS (viewBox, no fixed size); the label's white margin is the quiet zone."""
    return segno.make(url, error="m").svg_inline(omitsize=True, border=1, dark="#000000", light="#ffffff")
