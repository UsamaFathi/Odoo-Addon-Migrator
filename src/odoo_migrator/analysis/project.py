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

    @property
    def file_statistics(self) -> dict[str, int]:
        """Aggregate source-file counts for UI/report consumers."""
        counts = {"python": 0, "xml": 0, "javascript": 0, "csv": 0, "other": 0}
        known = {"python", "xml", "javascript", "csv"}
        for module in self.index.modules.values():
            for kind, count in module.files.items():
                if kind in known:
                    counts[kind] += count
            module_root = Path(module.path)
            for path in module_root.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() not in {".py", ".xml", ".js", ".csv"}:
                    counts["other"] += 1
        return counts

    @property
    def version_counts(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for module in self.index.modules.values():
            raw = str(module.manifest.get("version", ""))
            prefix = raw.split(".", 1)[0]
            if prefix.isdigit() and 14 <= int(prefix) <= 19:
                version = int(prefix)
                counts[version] = counts.get(version, 0) + 1
        return counts

    @property
    def detected_version(self) -> int | None:
        versions = self.version_counts
        return next(iter(versions)) if len(versions) == 1 else None

    @property
    def has_version_conflict(self) -> bool:
        return len(self.version_counts) > 1


def scan_custom_addons(root: Path) -> ProjectScan:
    root = Path(root).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Custom addons directory does not exist: {root}")
    index = SourceIndexer().index(root)
    if not index.modules:
        raise ValueError(f"No Odoo addons (__manifest__.py) found under: {root}")
    return ProjectScan(root, index)
