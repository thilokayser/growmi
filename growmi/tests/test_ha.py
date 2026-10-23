import httpx

from app.ha import HAClient
from datetime import datetime


def client(handler):
    return HAClient("http://ha/api", "tok", transport=httpx.MockTransport(handler))


def test_state_returns_value_and_sends_token():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"state": "Blüte"})

    assert client(handler).state("input_select.grow_phase") == "Blüte"
    assert seen["auth"] == "Bearer tok"


def test_state_none_for_unavailable_unknown_and_errors():
    for payload in ({"state": "unavailable"}, {"state": "unknown"}):
        assert client(lambda r, p=payload: httpx.Response(200, json=p)).state("x") is None
    assert client(lambda r: httpx.Response(404)).state("x") is None

    def boom(req):
        raise httpx.ConnectError("down")

    assert client(boom).state("x") is None


def test_history_keeps_only_numeric_values():
    body = [[{"state": "21.5"}, {"state": "unavailable"}, {"state": "22.5"}, {"state": "unknown"}]]
    c = client(lambda r: httpx.Response(200, json=body))
    assert c.history("sensor.t", datetime(2026, 10, 19), datetime(2026, 10, 20)) == [21.5, 22.5]


def test_history_empty_on_error():
    c = client(lambda r: httpx.Response(500))
    assert c.history("sensor.t", datetime(2026, 10, 19), datetime(2026, 10, 20)) == []
