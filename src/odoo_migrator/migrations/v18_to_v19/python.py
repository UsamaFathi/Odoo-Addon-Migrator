from __future__ import annotations

import ast
from pathlib import Path

from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.migrations.base import Change, Classification, MigrationRule
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.v15_to_v16.python import analyze as analyze_python


def _literal_constraints(value: ast.AST) -> list[tuple[str, str, str]] | None:
    if not isinstance(value, (ast.List, ast.Tuple)):
        return None
    result = []
    for item in value.elts:
        if not isinstance(item, (ast.Tuple, ast.List)) or len(item.elts) not in {2, 3}:
            return None
        values = [element.value if isinstance(element, ast.Constant) and isinstance(element.value, str) else None for element in item.elts]
        if values[0] is None or values[1] is None or (len(values) == 3 and values[2] is None):
            return None
        result.append((values[0], values[1], values[2] if len(values) == 3 else ""))
    return result


def _offsets(text: str) -> list[int]:
    values = [0]
    for line in text.splitlines(keepends=True):
        values.append(values[-1] + len(line))
    return values


def _constraint_rewrite(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return None
    imports_models = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "odoo"
        and any(alias.name == "models" for alias in node.names)
        for node in tree.body
    )
    if not imports_models:
        return None
    replacements = []
    offsets = _offsets(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "_sql_constraints"
            for target in node.targets
        ):
            continue
        constraints = _literal_constraints(node.value)
        segment = ast.get_source_segment(text, node)
        if constraints is None or not segment or "#" in segment:
            continue
        indent = " " * node.col_offset
        rendered = []
        for name, expression, message in constraints:
            if not name.isidentifier():
                return None
            rendered.append(f"{indent}_{name} = models.Constraint(")
            rendered.append(f"{indent}    {expression!r},")
            if message:
                rendered.append(f"{indent}    {message!r},")
            rendered.append(f"{indent})")
        start = offsets[node.lineno - 1]
        end = offsets[node.end_lineno - 1] + node.end_col_offset
        replacements.append((start, end, "\n".join(rendered)))
    if not replacements:
        return None
    updated = text
    for start, end, replacement in reversed(replacements):
        updated = updated[:start] + replacement + updated[end:]
    try:
        ast.parse(updated, filename=str(path))
    except SyntaxError:
        return None
    return updated


class SqlConstraintsToModelsConstraintRule(MigrationRule):
    """Convert the Odoo 18 ``_sql_constraints`` API to Odoo 19 constraints."""

    def __init__(self):
        super().__init__(
            18,
            19,
            "python.sql_constraints_to_models_constraint.18_to_19",
            "python",
            Classification.SAFE_AUTO_FIX,
            "Convert literal _sql_constraints declarations to models.Constraint declarations.",
            (
                "The pinned Odoo 19 ORM warns that _sql_constraints is no longer supported. "
                "The official odoo/upgrade_code/18.1-00-sql-constraint.py script converts "
                "literal constraint tuples to models.Constraint. This rule skips dynamic or "
                "comment-bearing declarations rather than rewriting them speculatively."
            ),
            True,
        )

    def apply(self, root: Path, dry_run: bool = False) -> list[Change]:
        changes: list[Change] = []
        for path in Path(root).rglob("*.py"):
            if path.name == "__manifest__.py" or "__pycache__" in path.parts:
                continue
            updated = _constraint_rewrite(path)
            if updated is None:
                continue
            changes.append(Change(
                self.rule_id,
                path,
                "Converted literal _sql_constraints to Odoo 19 models.Constraint declarations.",
                migration_step="18_to_19",
            ))
            if not dry_run:
                path.write_text(updated, encoding="utf-8")
        return changes


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> list[Finding]:
    findings = analyze_python(custom, source, target, diff, target_version=19, migration_step="18_to_19")
    for module in custom.modules.values():
        for path in Path(module.path).rglob("*.py"):
            if path.name == "__manifest__.py" or "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, UnicodeError, SyntaxError):
                continue
            if any(
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "_sql_constraints" for target in node.targets)
                for node in ast.walk(tree)
            ):
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED,
                    "python.sql_constraints.legacy",
                    module.name,
                    "Odoo 19 no longer supports _sql_constraints on model definitions.",
                    path=str(path),
                    rule_id="python.sql_constraints.legacy.18_to_19",
                    migration_step="18_to_19",
                    source_state="supported in Odoo 18",
                    target_state="deprecated/unsupported in Odoo 19",
                    suggested_action="Convert literal constraints to models.Constraint and review dynamic declarations.",
                ))
    return findings
