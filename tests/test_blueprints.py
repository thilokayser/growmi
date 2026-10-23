"""Structure checks for the blueprints (no Home Assistant needed): every input is used, every !input exists,
templates parse, and no personal entity ids slipped in."""
import glob
import re

import jinja2
import pytest
import yaml


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!input", lambda loader, node: ("INPUT", loader.construct_scalar(node)))
FILES = sorted(glob.glob("blueprints/automation/growmi/*.yaml"))


def walk(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)
    else:
        yield node


@pytest.mark.parametrize("path", FILES)
def test_blueprint_is_consistent(path):
    doc = yaml.load(open(path, encoding="utf-8"), Loader)
    bp = doc["blueprint"]
    assert bp["domain"] == "automation" and bp["name"].startswith("Growmi") and bp["homeassistant"]["min_version"]
    defined = set(bp["input"])
    body = {k: v for k, v in doc.items() if k != "blueprint"}
    used = {leaf[1] for leaf in walk(body) if isinstance(leaf, tuple) and leaf[0] == "INPUT"}
    assert used <= defined, f"unknown inputs: {used - defined}"
    assert defined <= used, f"unused inputs: {defined - used}"
    env = jinja2.Environment()
    for leaf in walk(body):
        if isinstance(leaf, str) and ("{{" in leaf or "{%" in leaf):
            env.parse(leaf)  # raises on a syntax error


def test_there_are_blueprints_and_no_personal_ids():
    assert len(FILES) >= 10
    text = "".join(open(f, encoding="utf-8").read() for f in FILES)
    assert not re.search(r"offgridtec|iphone|192\.168\.|\.local\b", text)
