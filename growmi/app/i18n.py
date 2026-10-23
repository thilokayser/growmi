"""German/English UI. German text in the code is the message id; `lang == "en"` looks it up in i18n_en.EN and falls
back to the German text, so a missing translation shows German instead of breaking a page.

Python code calls `tr("Platz {slot} ...", slot=1)`. Templates are rewritten when they are loaded: every run of
German text between tags becomes `{{ _("text with {0}", expr) }}` (see AutoTranslate), so templates stay readable."""
import re

from jinja2.ext import Extension
from markupsafe import Markup, escape

from .i18n_en import EN

LANGS = ("de", "en")
lang = "de"


def set_lang(setting: str | None, ha_language: str | None = None) -> str:
    """'de'/'en' as chosen; empty means follow Home Assistant (German stays German, anything else is English)."""
    global lang
    lang = setting if setting in LANGS else ("de" if (ha_language or "").lower().startswith("de") else "en")
    return lang


def _lookup(msg: str) -> str:
    return EN.get(msg, msg) if lang == "en" else msg


def tr(msg: str, *args, **kw) -> str:
    """Plain text for Python code and for template expressions; Jinja escapes it like any other value."""
    text = _lookup(msg)
    return text.format(*args, **kw) if args or kw else text


def static(msg: str, *args) -> Markup:
    """For text written in a template: trusted markup (may hold entities), the values filled in are escaped."""
    text = _lookup(msg)
    return Markup(text.format(*[escape(a) for a in args])) if args else Markup(text)


# ---- template rewriting ---------------------------------------------------------------------------------

TOKEN = re.compile(r"""
    (?P<comment>\{\#.*?\#\})
  | (?P<block>\{%.*?%\})
  | (?P<expr>\{\{.*?\}\})
  | (?P<script><(?:script|style)\b.*?</(?:script|style)>)
  | (?P<tag><(?:[^<>{]|\{\{.*?\}\}|\{%.*?%\}|\{\#.*?\#\})*>)
  | (?P<text>[^<{]+|[<{])
""", re.S | re.X)
LETTERS = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")
# values that bring their own markup, or whitespace control, split the sentence instead of filling a placeholder
BOUNDARY = re.compile(r"^\{\{-|-\}\}$|^\{\{\s*(icon|entity_field|_|caller)\s*\(|\|\s*safe\b")
ATTR = re.compile(r'\b(aria-label|placeholder|title|alt)="([^"]*)"')


def _literal(msgid: str) -> str:
    return '"' + msgid.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _call(parts: list) -> str:
    """parts: text strings and ('expr', code); returns the `{{ _(...) }}` call for them."""
    msgid, exprs = "", []
    for p in parts:
        if isinstance(p, tuple):
            msgid += "{%d}" % len(exprs)
            exprs.append(p[1])
        else:
            msgid += p
    msgid = re.sub(r"\s+", " ", msgid).strip()
    return "{{ _(" + ", ".join([_literal(msgid)] + exprs) + ") }}", msgid


def _flush(run: list, out: list, found: list) -> None:
    static_text = "".join(p for p in run if isinstance(p, str))
    if not LETTERS.search(static_text):
        out.extend(p if isinstance(p, str) else "{{" + p[1] + "}}" for p in run)
    else:
        joined = "".join(p if isinstance(p, str) else "\0" for p in run)
        lead = joined[:len(joined) - len(joined.lstrip())] if joined.strip() else ""
        trail = joined[len(joined.rstrip()):] if joined.strip() else ""
        parts = list(run)
        # whitespace around the sentence stays outside the call
        if lead and isinstance(parts[0], str):
            parts[0] = parts[0].lstrip()
        if trail and isinstance(parts[-1], str):
            parts[-1] = parts[-1].rstrip()
        call, msgid = _call(parts)
        out.append(lead + call + trail)
        found.append(msgid)
    run.clear()


def _attrs(tag: str, found: list) -> str:
    def repl(m):
        name, value = m.group(1), m.group(2)
        if "{%" in value or not LETTERS.search(re.sub(r"\{\{.*?\}\}", "", value)):
            return m.group(0)
        parts, pos = [], 0
        for e in re.finditer(r"\{\{(.*?)\}\}", value):
            parts += [value[pos:e.start()], ("expr", e.group(1))]
            pos = e.end()
        parts.append(value[pos:])
        call, msgid = _call(parts)
        found.append(msgid)
        return f'{name}="{call}"'
    return ATTR.sub(repl, tag)


def rewrite(source: str) -> tuple[str, list[str]]:
    """Returns the template source with its text wrapped in translation calls, and the message ids it contains."""
    out, run, found = [], [], []
    for m in TOKEN.finditer(source):
        kind, text = m.lastgroup, m.group()
        if kind == "text":
            run.append(text)
        elif kind == "expr" and not BOUNDARY.search(text):
            run.append(("expr", text[2:-2]))
        else:
            _flush(run, out, found)
            out.append(_attrs(text, found) if kind == "tag" else text)
    _flush(run, out, found)
    return "".join(out), found


class AutoTranslate(Extension):
    def preprocess(self, source, name, filename=None):
        return rewrite(source)[0]
