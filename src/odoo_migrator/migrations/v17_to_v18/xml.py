from __future__ import annotations

from dataclasses import dataclass
import os
import re
from pathlib import Path
import tempfile
from xml.parsers import expat

from odoo_migrator.analysis.compat import Finding
from odoo_migrator.migrations.base import Change, Classification, MigrationRule
from odoo_migrator.migrations.v15_to_v16.xml import analyze as analyze_views
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex

_VIEW_RECORD = "ir.ui.view"
_ACTION_MODE_RECORDS = frozenset({"ir.actions.act_window", "ir.actions.act_window.view"})


@dataclass(frozen=True, slots=True)
class _Replacement:
    start: int
    end: int
    value: bytes


@dataclass(slots=True)
class _Element:
    name: str
    attributes: dict[str, str]
    in_view_arch: bool = False
    action_view_mode: bool = False


def _tree_tag_replacements(data: bytes) -> list[_Replacement]:
    replacements: list[_Replacement] = []
    parser = expat.ParserCreate()
    stack: list[_Element] = []

    def start(name: str, attributes: dict[str, str]) -> None:
        parent = stack[-1] if stack else None
        record_model = parent.attributes.get("model") if parent and parent.name == "record" else None
        in_view_arch = bool(parent and parent.in_view_arch)
        if parent and parent.name == "record" and record_model == _VIEW_RECORD and name == "field":
            in_view_arch = attributes.get("name") == "arch"
        element = _Element(name, attributes, in_view_arch=in_view_arch)
        stack.append(element)
        if name == "tree" and in_view_arch:
            start_offset = parser.CurrentByteIndex
            replacements.append(_Replacement(start_offset + 1, start_offset + 5, b"list"))

    def end(name: str) -> None:
        if name == "tree" and stack and stack[-1].name == name and stack[-1].in_view_arch:
            close_offset = parser.CurrentByteIndex
            if data[close_offset:close_offset + 6] == b"</tree":
                replacements.append(_Replacement(close_offset + 2, close_offset + 6, b"list"))
        if stack:
            stack.pop()

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(data, True)
    except expat.ExpatError:
        return []
    return replacements


def _action_view_mode_replacements(data: bytes) -> list[_Replacement]:
    replacements: list[_Replacement] = []
    parser = expat.ParserCreate()
    stack: list[_Element] = []

    def start(name: str, attributes: dict[str, str]) -> None:
        parent = stack[-1] if stack else None
        is_action_field = bool(
            parent
            and parent.name == "record"
            and parent.attributes.get("model") in _ACTION_MODE_RECORDS
            and name == "field"
            and attributes.get("name") == "view_mode"
        )
        stack.append(_Element(name, attributes, action_view_mode=is_action_field))

    def text(value: str) -> None:
        if not value or not stack or not stack[-1].action_view_mode:
            return
        # view_mode is an ASCII comma-separated field. Skip entities or
        # unusual encodings rather than risking an offset mismatch.
        if any(ord(char) > 127 for char in value):
            return
        start_offset = parser.CurrentByteIndex
        raw = value.encode("ascii")
        if data[start_offset:start_offset + len(raw)] != raw:
            return
        cursor = 0
        for part in value.split(","):
            leading = len(part) - len(part.lstrip())
            trailing = len(part) - len(part.rstrip())
            if part.strip() == "tree":
                replacement = part[:leading] + "list" + (part[len(part) - trailing:] if trailing else "")
                replacements.append(_Replacement(start_offset + cursor, start_offset + cursor + len(part), replacement.encode("ascii")))
            cursor += len(part) + 1

    def end(name: str) -> None:
        if stack:
            stack.pop()

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    try:
        parser.Parse(data, True)
    except expat.ExpatError:
        return []
    return replacements


def _apply_replacements(data: bytes, replacements: list[_Replacement]) -> bytes:
    result = data
    for replacement in sorted(replacements, key=lambda item: item.start, reverse=True):
        result = result[:replacement.start] + replacement.value + result[replacement.end:]
    return result


def _apply_xml_rule(root: Path, rule_id: str, replacement_builder, description: str, dry_run: bool) -> list[Change]:
    changes: list[Change] = []
    for path in Path(root).rglob("*.xml"):
        try:
            original = path.read_bytes()
        except (OSError, UnicodeError):
            continue
        replacements = replacement_builder(original)
        if not replacements:
            continue
        updated = _apply_replacements(original, replacements)
        if updated == original:
            continue
        changes.append(Change(rule_id, path, description, migration_step="17_to_18"))
        if not dry_run:
            temporary_path: str | None = None
            try:
                descriptor, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(updated)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, path)
                temporary_path = None
            except (OSError, UnicodeError):
                if temporary_path:
                    try:
                        os.unlink(temporary_path)
                    except OSError:
                        pass
                # A failed atomic write must not be reported as a completed change.
                changes.pop()
    return changes


class TreeToListRule(MigrationRule):
    """Convert Odoo view architecture tree elements without rebuilding XML."""

    def __init__(self):
        super().__init__(
            17,
            18,
            "xml.view_root.tree_to_list.17_to_18",
            "xml",
            Classification.SAFE_AUTO_FIX,
            "Rename Odoo 17 tree view architecture elements to Odoo 18 list elements.",
            (
                "Odoo 17 source uses tree elements for root and embedded relational "
                "view architectures; Odoo 18 uses list elements for both. The "
                "structured edit is limited to ir.ui.view arch fields and changes "
                "only parser-confirmed element-name spans."
            ),
            True,
        )

    def apply(self, root: Path, dry_run: bool=False) -> list[Change]:
        return _apply_xml_rule(
            root,
            self.rule_id,
            _tree_tag_replacements,
            "Converted ir.ui.view tree architecture elements to list without rewriting unrelated XML.",
            dry_run,
        )


class ActionViewModeTreeToListRule(MigrationRule):
    """Convert only verified action view_mode fields from tree to list."""

    def __init__(self):
        super().__init__(
            17,
            18,
            "xml.action_view_mode.tree_to_list.17_to_18",
            "xml",
            Classification.SAFE_AUTO_FIX,
            "Rename tree view modes to list in Odoo action records.",
            (
                "Odoo 17 odoo/addons/base/models/ir_actions.py:280 and :367 use "
                "tree in ir.actions.act_window and VIEW_TYPES; Odoo 18 :312 and "
                ":418 use list. The same semantic selection is used by both "
                "ir.actions.act_window.view.view_mode and the parent action "
                "view_mode field."
            ),
            True,
        )

    def apply(self, root: Path, dry_run: bool=False) -> list[Change]:
        return _apply_xml_rule(
            root,
            self.rule_id,
            _action_view_mode_replacements,
            "Converted action view_mode tree tokens to list without rewriting unrelated XML.",
            dry_run,
        )



_XPATH_EXPR_ATTR = re.compile(
    r"(?P<prefix><xpath\b[^<>]*?\bexpr\s*=\s*)(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
def _rewrite_xpath_tree_nodes(expression: str) -> str:
    output: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(expression):
        char = expression[index]
        if quote:
            output.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            output.append(char)
            index += 1
            continue
        if expression.startswith("tree", index):
            previous_ok = (
                index == 0
                or expression[index - 1] == "/"
                or (index >= 2 and expression[index - 2:index] == "::")
            )
            end = index + 4
            next_ok = end == len(expression) or expression[end] in {"/", "["}
            if previous_ok and next_ok:
                output.append("list")
                index = end
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _xpath_tree_to_list_replacements(data: bytes) -> list[_Replacement]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    replacements: list[_Replacement] = []
    for match in _XPATH_EXPR_ATTR.finditer(text):
        expression = match.group("value")
        rewritten = _rewrite_xpath_tree_nodes(expression)
        if rewritten == expression:
            continue
        start_chars = match.start("value")
        end_chars = match.end("value")
        start = len(text[:start_chars].encode("utf-8"))
        end = len(text[:end_chars].encode("utf-8"))
        replacements.append(_Replacement(start, end, rewritten.encode("utf-8")))
    return replacements


class XPathTreeToListRule(MigrationRule):
    """Convert XPath node tests that target Odoo 17 tree views to Odoo 18 list views."""

    def __init__(self):
        super().__init__(
            17,
            18,
            "xml.xpath.tree_to_list.17_to_18",
            "xml",
            Classification.SAFE_AUTO_FIX,
            "Rename XPath tree node tests to list for Odoo 18 inherited views.",
            (
                "The edit is restricted to expr attributes on xpath elements and only replaces "
                "the XPath node-test token 'tree' after '/' or '::'. String literals and attribute "
                "names are not rewritten."
            ),
            True,
        )

    def apply(self, root: Path, dry_run: bool = False) -> list[Change]:
        return _apply_xml_rule(
            root,
            self.rule_id,
            _xpath_tree_to_list_replacements,
            "Converted XPath tree node tests to list without rewriting unrelated XML.",
            dry_run,
        )

def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> list[Finding]:
    return analyze_views(custom, source, target, target_version=18, migration_step="17_to_18")
