from urllib.parse import urlparse

import segno

from . import config

DEFAULT_URL = "http://homeassistant.local:8123"


def slot_urls(options: dict, ha, secret: str | None = None) -> dict[int, str]:
    base = (options.get("ha_url") or ha.config_url() or DEFAULT_URL).rstrip("/")
    if secret:  # direct LAN address with a secret instead of the ingress path (ingress refuses plain browsers with 401)
        host = urlparse(base).hostname or "homeassistant.local"
        port = int(options.get("public_port", 8100) or 8100)
        return {slot: f"http://{host}:{port}/s/{secret}/platz/{slot}" for slot in config.slots()}
    entry = ha.ingress_entry()
    return {slot: f"{base}{entry}/platz/{slot}" for slot in config.slots()}


def qr_svg(url: str) -> str:
    return segno.make(url, error="m").svg_inline(scale=5, border=2, dark="#000000", light="#ffffff")
