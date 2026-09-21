from pathlib import Path
import xml.etree.ElementTree as ET

from odoo_migrator.analysis.compat import Finding
from odoo_migrator.migrations.base import Change, Classification, MigrationRule
from odoo_migrator.migrations.v15_to_v16.xml import analyze as analyze_views
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex


class TreeToListRule(MigrationRule):
    """Convert only tree elements inside ir.ui.view architecture XML."""

    def __init__(self):
        super().__init__(
            17,
            18,
            "xml.view_root.tree_to_list.17_to_18",
            "xml",
            Classification.SAFE_AUTO_FIX,
            "Rename Odoo 17 tree view roots to the Odoo 18 list view root.",
            (
                "Odoo 17 source uses tree view roots in "
                "odoo/addons/base/models/ir_ui_view.py and official 17.0 XML; "
                "Odoo 18 validates list roots in the same file and official 18.0 XML "
                "uses list roots. Only ir.ui.view architecture is transformed."
            ),
            True,
        )

    def apply(self, root: Path, dry_run: bool = False) -> list[Change]:
        changes = []
        for path in Path(root).rglob("*.xml"):
            try:
                tree = ET.parse(path)
            except (ET.ParseError, OSError, UnicodeError):
                continue
            changed = False
            for record in tree.getroot().iter("record"):
                if record.attrib.get("model") != "ir.ui.view":
                    continue
                for architecture in record.findall("field"):
                    if architecture.attrib.get("name") != "arch":
                        continue
                    for content in architecture:
                        for node in content.iter():
                            if node.tag == "tree":
                                node.tag = "list"
                                changed = True
            if not changed:
                continue
            changes.append(Change(self.rule_id, path, "Converted ir.ui.view <tree> architecture roots to <list>."))
            if not dry_run:
                tree.write(path, encoding="unicode")
        return changes


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> list[Finding]:
    return analyze_views(custom, source, target, target_version=18, migration_step="17_to_18")
