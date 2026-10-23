import copy

import pytest

from app import config, db, i18n


class FakeHA:
    """Stands in for ha.HAClient: fixed answers, no network."""

    def __init__(self, states=None, histories=None):
        self.states = states or {}
        self.histories = histories or {}
        self.history_calls = []
        self.service_calls = []
        self.published = {}
        self.fail = False
        self.responses = {}
        self.state_histories = {}
        self.point_histories = {}

    def state(self, entity_id):
        return self.states.get(entity_id)

    def call_service_response(self, domain, service, data):
        return self.responses.get((domain, service))

    def language(self):
        return None

    def all_states(self):
        return sorted(self.states)

    def find_entity(self, prefix):
        return next((k for k in self.states if k.startswith(prefix)), None)

    def history_points(self, entity_id, start, end):
        return list(self.point_histories.get(entity_id, []))

    def history_states(self, entity_id, start, end):
        return list(self.state_histories.get(entity_id, []))

    def config_url(self):
        return None

    def ingress_entry(self):
        return "/api/hassio_ingress/abc"

    def set_state(self, entity_id, state, attributes=None):
        self.published[entity_id] = (state, attributes or {})
        return True

    def call_service(self, domain, service, data):
        self.service_calls.append((domain, service, data))
        return not self.fail

    def history(self, entity_id, start, end):
        self.history_calls.append((entity_id, start))
        return list(self.histories.get(entity_id, []))


@pytest.fixture(autouse=True)
def legacy_config():
    """Tests run on the entities the first install had hard-coded; test_config.py tests the empty case."""
    config.current = copy.deepcopy(config.EXAMPLE)
    i18n.set_lang("de")
    yield
    config.current = copy.deepcopy(config.EMPTY)
    i18n.set_lang("de")


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    yield c
    c.close()


@pytest.fixture
def ha():
    return FakeHA()


class Web:
    def __init__(self, path, public_secret=None):
        from fastapi.testclient import TestClient
        from app.main import create_app
        self.data_dir = str(path)
        self.ha = FakeHA()
        self.client = TestClient(create_app(self.data_dir, self.ha, run_jobs=False, public_secret=public_secret), follow_redirects=False)
        config.save(self.conn(), config.EXAMPLE)
        i18n.set_lang(config.current["lang"])

    def conn(self):
        return db.connect(f"{self.data_dir}/growlog.db")


@pytest.fixture
def web(tmp_path):
    return Web(tmp_path)


@pytest.fixture
def pub(tmp_path):
    """The LAN-facing app for QR tags: everything lives under /s/<secret>/ and only quick pages are allowed."""
    return Web(tmp_path, public_secret="secret123")
