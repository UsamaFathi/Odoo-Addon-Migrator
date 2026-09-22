from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from odoo_migrator.sources.registry import SourceMode, source_spec
from odoo_migrator.ui.widgets.design_system import SurfaceCard, StatusBadge


class SourceVersionCard(SurfaceCard):
    def __init__(self, version: int, parent=None):
        super().__init__(parent); self.version = version
        layout = QVBoxLayout(self); layout.setContentsMargins(12, 10, 12, 10); layout.setSpacing(4)
        self.heading = QLabel(f"Odoo {version}"); self.heading.setObjectName("sectionTitle"); layout.addWidget(self.heading)
        self.status = StatusBadge("Download required", "badgeWarning"); layout.addWidget(self.status)
        self.mode = QLabel("Verified Snapshot"); self.mode.setObjectName("muted"); layout.addWidget(self.mode)
        self.commit = QLabel(""); self.commit.setObjectName("muted"); layout.addWidget(self.commit)

    def set_snapshot(self, snapshot) -> None:
        expected = source_spec(self.version).verified_commit or "unknown"
        ready = bool(snapshot and snapshot.source_mode is SourceMode.VERIFIED_SNAPSHOT and snapshot.expected_commit == snapshot.actual_commit)
        actual = snapshot.actual_commit if snapshot else expected
        self.status.setText("Ready locally" if ready else "Download required")
        self.status.set_role("badgeSuccess" if ready else "badgeWarning")
        self.commit.setText((actual or expected)[:12] + "…"); self.commit.setToolTip(actual or expected)


class SourceStatus(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.cards: list[SourceVersionCard] = []
        self.label = QLabel("Select versions to check the local verified source cache."); self.label.setObjectName("muted"); self.label.setVisible(False)
        self.layout = QVBoxLayout(self); self.layout.setContentsMargins(0, 0, 0, 0); self.layout.setSpacing(7)
        title = QLabel("Official Odoo sources"); title.setObjectName("sectionTitle"); self.layout.addWidget(title)
        self.row = QHBoxLayout(); self.row.setSpacing(8); self.layout.addLayout(self.row); self.layout.addWidget(self.label)

    def set_versions(self, versions: list[int], snapshots=None) -> None:
        while self.row.count():
            item = self.row.takeAt(0); widget = item.widget()
            if widget: widget.deleteLater()
        self.cards = []; lines = []
        for version in versions:
            card = SourceVersionCard(version); card.set_snapshot((snapshots or {}).get(version) if snapshots else None)
            self.cards.append(card); self.row.addWidget(card); lines.append(f"Odoo {version} • {card.status.text()}")
        self.row.addStretch()
        details = []
        for card, line in zip(self.cards, lines):
            details.append(line.replace(" • ", "  •  ") + "\nVerified Snapshot\n" + card.commit.text())
        self.label.setText("\n\n".join(details) if details else "No implemented target is available from this source version.")
