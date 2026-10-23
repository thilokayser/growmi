from . import config


def strompreis(ha, options: dict) -> float:
    """EUR per kWh: the HA helper wins (editable on the dashboard), the add-on option is the fallback."""
    try:
        v = float(str(config.state(ha, "price")).replace(",", "."))
        if v > 0:
            return v
    except ValueError:
        pass
    return float(options.get("strompreis_eur_kwh") or 0)
