"""Collects every message id the app can show: template text, tr() calls in Python and the fixed word lists."""
import ast
import glob
import os
import re

from app import cockpit, entries, i18n, plants, tasks

APP = os.path.join(os.path.dirname(__file__), "..", "app")


def template_ids() -> set[str]:
    ids = set()
    for path in glob.glob(f"{APP}/templates/*.html"):
        src = open(path, encoding="utf-8").read()
        ids |= set(i18n.rewrite(src)[1])
        ids |= {m[2] for m in re.finditer(r"""\btr\((['"])(.*?)\1\)""", src)}
        for line in src.splitlines():  # label and hint of the settings macro
            if "entity_field(" in line and "macro" not in line:
                args = re.findall(r"'((?:[^'\\]|\\.)*)'", line)
                ids |= {args[1]} | ({args[3]} if len(args) > 3 else set())
    return ids


def python_ids() -> set[str]:
    ids = set()
    for path in glob.glob(f"{APP}/*.py"):
        for node in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args \
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                ids.add(node.args[0].value)
    return ids


def word_list_ids() -> set[str]:
    words = {r[1] for r in tasks.RULES} | set(plants.PHASES) | set(plants.BOX_PHASES) | set(entries.ARTEN) \
        | set(entries.TAGS) | set(cockpit.MODES) | set(cockpit.EXHAUST_MODES) | set(plants.TYPEN.values())
    return {w for w in words if w}


def collect() -> set[str]:
    return template_ids() | python_ids() | word_list_ids()
