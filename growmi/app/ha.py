import logging
import os
from datetime import datetime

import httpx

log = logging.getLogger("growmi.ha")


class HAClient:
    """Read-only HA access. Every failure degrades to None / [] so callers never crash."""

    def __init__(self, base_url: str, token: str, transport: httpx.BaseTransport | None = None):
        self.token = token
        self.http = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {token}"},
                                 timeout=10, transport=transport)

    @classmethod
    def from_env(cls) -> "HAClient":
        return cls("http://supervisor/core/api", os.environ.get("SUPERVISOR_TOKEN", ""))

    def state(self, entity_id: str) -> str | None:
        try:
            r = self.http.get(f"/states/{entity_id}", timeout=3)  # pages call this, keep it snappy
            if r.status_code != 200:
                return None
            value = r.json().get("state")
        except (httpx.HTTPError, ValueError) as e:
            log.warning("state %s failed: %s", entity_id, e)
            return None
        return None if value in (None, "unavailable", "unknown") else value

    def all_states(self) -> list[str]:
        """Every entity id HA knows, for the settings page pick lists."""
        try:
            r = self.http.get("/states")
            return sorted(s["entity_id"] for s in r.json()) if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            log.warning("states failed: %s", e)
            return []

    def history(self, entity_id: str, start: datetime, end: datetime) -> list[float]:
        try:
            r = self.http.get(f"/history/period/{start.isoformat()}",
                              params={"filter_entity_id": entity_id, "end_time": end.isoformat(),
                                      "minimal_response": "", "no_attributes": ""})
            if r.status_code != 200:
                return []
            series = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("history %s failed: %s", entity_id, e)
            return []
        values = []
        for point in series[0] if series else []:
            try:
                values.append(float(point["state"]))
            except (KeyError, TypeError, ValueError):
                pass  # unavailable / unknown
        return values

    def call_service(self, domain: str, service: str, data: dict) -> bool:
        try:
            return self.http.post(f"/services/{domain}/{service}", json=data).status_code == 200
        except httpx.HTTPError as e:
            log.warning("service %s.%s failed: %s", domain, service, e)
            return False

    def set_state(self, entity_id: str, state, attributes: dict | None = None) -> bool:
        """Publishes a virtual entity (lives until HA restarts; the add-on republishes every minute)."""
        try:
            r = self.http.post(f"/states/{entity_id}", json={"state": str(state), "attributes": attributes or {}})
            return r.status_code in (200, 201)
        except httpx.HTTPError as e:
            log.warning("set_state %s failed: %s", entity_id, e)
            return False

    def ingress_entry(self) -> str:
        """'/api/hassio_ingress/<token>' of this add-on, as long as it stays installed."""
        try:
            r = httpx.get("http://supervisor/addons/self/info", headers={"Authorization": f"Bearer {self.token}"},
                          timeout=5)
            return (r.json().get("data") or {}).get("ingress_entry") or ""
        except (httpx.HTTPError, ValueError):
            return ""

    def config_url(self) -> str | None:
        try:
            c = self.http.get("/config", timeout=5).json()
            return c.get("internal_url") or c.get("external_url")
        except (httpx.HTTPError, ValueError):
            return None

    def language(self) -> str | None:
        try:
            return self.http.get("/config", timeout=5).json().get("language")
        except (httpx.HTTPError, ValueError, AttributeError):
            return None

    def call_service_response(self, domain: str, service: str, data: dict) -> dict | None:
        try:
            r = self.http.post(f"/services/{domain}/{service}?return_response", json=data)
            return r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as e:
            log.warning("service %s.%s failed: %s", domain, service, e)
            return None

    def find_entity(self, prefix: str) -> str | None:
        try:
            for st in self.http.get("/states", timeout=5).json():
                if st["entity_id"].startswith(prefix):
                    return st["entity_id"]
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        return None

    def history_states(self, entity_id: str, start, end) -> list:
        """[(datetime, state)] of a switch-like entity, including its state at `start`."""
        try:
            r = self.http.get(f"/history/period/{start.isoformat()}",
                              params={"filter_entity_id": entity_id, "end_time": end.isoformat(),
                                      "minimal_response": "", "no_attributes": ""})
            rows = r.json()[0] if r.status_code == 200 and r.json() else []
            return [(datetime.fromisoformat(p["last_changed"]).astimezone().replace(tzinfo=None), p["state"])
                    for p in rows if "last_changed" in p]
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return []

    def history_points(self, entity_id: str, start, end) -> list:
        """[(datetime, float)] of a numeric sensor with real timestamps; non-numeric readings are dropped."""
        try:
            r = self.http.get(f"/history/period/{start.isoformat()}",
                              params={"filter_entity_id": entity_id, "end_time": end.isoformat(),
                                      "minimal_response": "", "no_attributes": ""})
            rows = r.json()[0] if r.status_code == 200 and r.json() else []
        except (httpx.HTTPError, ValueError, IndexError):
            return []
        out = []
        for p in rows:
            try:
                out.append((datetime.fromisoformat(p["last_changed"]).astimezone().replace(tzinfo=None), float(p["state"])))
            except (KeyError, TypeError, ValueError):
                pass
        return out
