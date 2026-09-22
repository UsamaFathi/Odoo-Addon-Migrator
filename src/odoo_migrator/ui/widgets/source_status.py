from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout

from odoo_migrator.sources.registry import SourceMode, source_spec


class SourceStatus(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Odoo source status", parent)
        self.label = QLabel("Select versions to check the local verified source cache.")
        self.label.setWordWrap(True)
        layout = QVBoxLayout(self); layout.addWidget(self.label)

    def set_versions(self, versions: list[int], snapshots=None) -> None:
        lines = []
        for version in versions:
            snapshot = (snapshots or {}).get(version) if snapshots else None
            expected = source_spec(version).verified_commit or "unknown"
            if snapshot and snapshot.source_mode is SourceMode.VERIFIED_SNAPSHOT and snapshot.expected_commit == snapshot.actual_commit:
                lines.append(f"Odoo {version}  •  Ready locally\nVerified Snapshot\n{snapshot.actual_commit[:12]}...")
            else:
                lines.append(f"Odoo {version}  •  Download required\nVerified Snapshot\n{expected[:12]}...")
        self.label.setText("\n\n".join(lines) if lines else "No implemented target is available from this source version.")
