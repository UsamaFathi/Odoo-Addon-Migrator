from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

from odoo_migrator.sources.indexer import OdooIndex, SourceIndexer


@dataclass(frozen=True, slots=True)
class ProjectScan:
    root: Path
    index: OdooIndex

    @property
    def module_count(self) -> int:
        return len(self.index.modules)


def scan_custom_addons(root: Path) -> ProjectScan:
    root = Path(root).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Custom addons directory does not exist: {root}")
    index = SourceIndexer().index(root)
    if not index.modules:
        raise ValueError(f"No Odoo addons (__manifest__.py) found under: {root}")
    return ProjectScan(root, index)
