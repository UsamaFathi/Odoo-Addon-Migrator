from __future__ import annotations

from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from odoo_migrator.ui.widgets.design_system import SectionHeader, StatusBadge, SurfaceCard


class MigrationPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.stage = QLabel("Preparing migration…"); self.stage.setObjectName("sectionTitle")
        self.destination = QLabel(); self.destination.setWordWrap(True); self.destination.setObjectName("muted")
        self.progress = QProgressBar(); self.progress.setRange(0, 100)
        self.safety = StatusBadge("Your original project will not be modified.", "badgeInfo")
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 20); layout.setSpacing(14)
        layout.addWidget(SectionHeader("Migration", "A safe, staged copy is being prepared for the target Odoo version.")); layout.addWidget(self.safety)
        card = SurfaceCard(); inner = QVBoxLayout(card); inner.setContentsMargins(18, 18, 18, 18); inner.addWidget(self.stage); inner.addWidget(self.destination); inner.addWidget(self.progress); layout.addWidget(card); layout.addStretch()

    def set_destination(self, path) -> None:
        self.destination.setText(f"Output folder\n{path}")

    def set_progress(self, stage: str, percent: int) -> None:
        self.stage.setText(stage); self.progress.setValue(percent)

    def set_busy(self, busy: bool) -> None:
        self.progress.setEnabled(busy)
