from __future__ import annotations

from PySide6.QtWidgets import QLabel, QLayout, QProgressBar, QSizePolicy, QVBoxLayout, QWidget

from odoo_migrator.ui.widgets.design_system import SectionHeader, StatusBadge, SurfaceCard


class MigrationPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.stage = QLabel("Preparing migration…"); self.stage.setObjectName("sectionTitle")
        self.destination = QLabel(); self.destination.setWordWrap(True); self.destination.setObjectName("muted")
        self.progress = QProgressBar(); self.progress.setRange(0, 100)
        self.safety = StatusBadge("Your original project will not be modified.", "badgeInfo")
        layout = QVBoxLayout(self); layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize); layout.setContentsMargins(28, 24, 28, 28); layout.setSpacing(16)
        layout.addWidget(SectionHeader("Migration", "A safe, staged copy is being prepared for the target Odoo version.")); layout.addWidget(self.safety)
        self.progress_card = SurfaceCard(); self.progress_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        inner = QVBoxLayout(self.progress_card); inner.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize); inner.setContentsMargins(20, 20, 20, 20); inner.setSpacing(14); inner.addWidget(self.stage); inner.addWidget(self.destination); inner.addWidget(self.progress); layout.addWidget(self.progress_card); layout.addStretch()

    def set_destination(self, path) -> None:
        self.destination.setText(f"Output folder\n{path}")

    def set_progress(self, stage: str, percent: int) -> None:
        self.stage.setText(stage); self.progress.setValue(percent)

    def set_busy(self, busy: bool) -> None:
        self.progress.setEnabled(busy)
