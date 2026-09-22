from __future__ import annotations

import ast
import html
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from odoo_migrator.migrations.base import Change, Classification, MigrationRule


_TAG_RE = re.compile(r"<(?P<name>[A-Za-z_][\w:.-]*)(?P<body>[^<>]*?)>", re.DOTALL)
_ATTR_RE = re.compile(
    r"(?P<lead>\s+)(?P<name>[A-Za-z_][\w:.-]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_FIELD = re.compile(r"^[A-Za-z_]\w*$")
_SUPPORTED_KEYS = frozenset({"invisible", "readonly", "required", "column_invisible"})


class _UnsupportedModifier(ValueError):
    pass


def _literal(value) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    if isinstance(value, (str, int, float)):
        return repr(value)
    if isinstance(value, (tuple, list)):
        rendered = ", ".join(_literal(item) for item in value)
        if isinstance(value, tuple):
            return f"({rendered}{',' if len(value) == 1 else ''})"
        return f"[{rendered}]"
    raise _UnsupportedModifier(f"unsupported literal: {type(value).__name__}")


def _term(term) -> str:
    if not isinstance(term, (tuple, list)) or len(term) != 3:
        raise _UnsupportedModifier("modifier term must contain exactly three items")
    field, operator, value = term
    if not isinstance(field, str) or not _FIELD.fullmatch(field):
        raise _UnsupportedModifier(f"unsupported field expression: {field!r}")
    operators = {
        "=": "==",
        "!=": "!=",
        "<": "<",
        "<=": "<=",
        ">": ">",
        ">=": ">=",
        "in": "in",
        "not in": "not in",
    }
    rendered_operator = operators.get(operator)
    if rendered_operator is None:
        raise _UnsupportedModifier(f"unsupported modifier operator: {operator!r}")
    return f"{field} {rendered_operator} {_literal(value)}"


def _parse_prefix(tokens: list, position: int = 0) -> tuple[str, int]:
    if position >= len(tokens):
        raise _UnsupportedModifier("incomplete modifier expression")
    token = tokens[position]
    if token == "!":
        child, end = _parse_prefix(tokens, position + 1)
        return f"not ({child})", end
    if token in {"|", "&"}:
        left, next_position = _parse_prefix(tokens, position + 1)
        right, end = _parse_prefix(tokens, next_position)
        operator = "or" if token == "|" else "and"
        return f"({left}) {operator} ({right})", end
    return _term(token), position + 1


def _domain_expression(domain) -> str:
    if not isinstance(domain, (list, tuple)) or not domain:
        raise _UnsupportedModifier("modifier domain must be a non-empty list")
    tokens = list(domain)
    if tokens[0] in {"|", "&", "!"}:
        expression, end = _parse_prefix(tokens)
        if end != len(tokens):
            trailing = [_term(item) for item in tokens[end:]]
            expression = " and ".join([f"({expression})", *(f"({item})" for item in trailing)])
        return expression
    return " and ".join(f"({_term(item)})" for item in tokens)


def _merge(existing: str | None, added: str) -> str:
    existing = (existing or "").strip()
    if not existing:
        return added
    if existing in {"0", "False", "false"}:
        return added
    if existing in {"1", "True", "true"}:
        return "True"
    return f"({existing}) or ({added})"


def _rewrite_tag(match: re.Match[str]) -> tuple[str, bool]:
    name = match.group("name")
    body = match.group("body")
    attrs = list(_ATTR_RE.finditer(body))
    if not attrs:
        return match.group(0), False

    values = {item.group("name"): html.unescape(item.group("value")) for item in attrs}
    additions: dict[str, str] = {}
    remove_names: set[str] = set()

    raw_attrs = values.get("attrs")
    if raw_attrs is not None:
        try:
            parsed = ast.literal_eval(raw_attrs)
        except (ValueError, SyntaxError):
            return match.group(0), False
        if not isinstance(parsed, dict) or not parsed or any(key not in _SUPPORTED_KEYS for key in parsed):
            return match.group(0), False
        try:
            for key, domain in parsed.items():
                additions[key] = _merge(values.get(key), _domain_expression(domain))
        except _UnsupportedModifier:
            return match.group(0), False
        remove_names.add("attrs")

    raw_states = values.get("states")
    if raw_states is not None:
        states = tuple(item.strip() for item in raw_states.split(",") if item.strip())
        if not states:
            return match.group(0), False
        additions["invisible"] = _merge(values.get("invisible"), f"state not in {_literal(states)}")
        remove_names.add("states")

    if not remove_names:
        return match.group(0), False

    pieces: list[str] = []
    cursor = 0
    replaced_inline: set[str] = set()
    for item in attrs:
        pieces.append(body[cursor:item.start()])
        attr_name = item.group("name")
        if attr_name in remove_names:
            cursor = item.end()
            continue
        if attr_name in additions:
            escaped = html.escape(additions[attr_name], quote=True)
            pieces.append(f'{item.group("lead")}{attr_name}="{escaped}"')
            replaced_inline.add(attr_name)
        else:
            pieces.append(item.group(0))
        cursor = item.end()
    pieces.append(body[cursor:])
    rewritten_body = "".join(pieces)
    stripped = rewritten_body.rstrip()
    trailing = rewritten_body[len(stripped):]
    self_closing = stripped.endswith("/")
    if self_closing:
        rewritten_body = stripped[:-1]
    for key, expression in additions.items():
        if key not in replaced_inline:
            rewritten_body += f' {key}="{html.escape(expression, quote=True)}"'
    if self_closing:
        rewritten_body += "/" + trailing

    return f"<{name}{rewritten_body}>", True


def _rewrite_xml(text: str) -> tuple[str, bool]:
    changed = False
    output: list[str] = []
    cursor = 0
    for match in _TAG_RE.finditer(text):
        output.append(text[cursor:match.start()])
        rewritten, tag_changed = _rewrite_tag(match)
        output.append(rewritten)
        changed = changed or tag_changed
        cursor = match.end()
    output.append(text[cursor:])
    return "".join(output), changed


class LegacyAttrsStatesRule(MigrationRule):
    """Convert deterministic Odoo 16 attrs/states modifiers to Odoo 17 inline expressions."""

    def __init__(self):
        super().__init__(
            16,
            17,
            "xml.modifiers.attrs_states_to_inline.16_to_17",
            "xml",
            Classification.SAFE_AUTO_FIX,
            "Convert deterministic attrs/states view modifiers to Odoo 17 inline expressions.",
            (
                "Odoo 17 rejects legacy attrs/states view modifiers. This rule handles only "
                "literal modifier dictionaries and deterministic boolean domains using standard "
                "comparison/in/not-in operators; unsupported expressions remain for review."
            ),
            True,
        )

    def apply(self, root: Path, dry_run: bool = False) -> list[Change]:
        changes: list[Change] = []
        for path in Path(root).rglob("*.xml"):
            try:
                original = path.read_text(encoding="utf-8")
                ET.fromstring(original)
            except (OSError, UnicodeError, ET.ParseError):
                continue
            updated, changed = _rewrite_xml(original)
            if not changed or updated == original:
                continue
            try:
                ET.fromstring(updated)
            except ET.ParseError:
                continue
            changes.append(Change(
                self.rule_id,
                path,
                "Converted legacy attrs/states modifiers to inline boolean expressions.",
                migration_step="16_to_17",
            ))
            if not dry_run:
                path.write_text(updated, encoding="utf-8")
        return changes
