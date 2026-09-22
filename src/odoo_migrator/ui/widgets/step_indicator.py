from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from odoo_migrator.ui.version import display_version
from odoo_migrator import __version__


class StepIndicator(QWidget):
    STEPS = (("Project", "Choose and scan your addons"), ("Analyze", "Compare official sources"), ("Review", "Inspect findings and fixes"), ("Migrate", "Create a safe output copy"), ("Validate", "Review static validation"))

    def __init__(self, parent=None):
        super().__init__(parent); self.setObjectName("sidebar")
        layout = QVBoxLayout(self); layout.setContentsMargins(18, 24, 18, 18); layout.setSpacing(2)
        brand = QLabel("OAM"); brand.setStyleSheet("color:#F4D8E9;font-size:24px;font-weight:800;"); layout.addWidget(brand)
        product = QLabel("Odoo Addon\nMigrator"); product.setStyleSheet("color:white;font-size:16px;font-weight:700;"); layout.addWidget(product)
        version = QLabel(f"v{display_version(__version__)}"); version.setStyleSheet("color:#A9B2C0;font-size:11px;"); layout.addWidget(version); layout.addSpacing(26)
        self.items = []
        for index, (title, subtitle) in enumerate(self.STEPS):
            item = QFrame(); item.setObjectName("workflowItem")
            item_layout = QHBoxLayout(item); item_layout.setContentsMargins(8, 9, 8, 9); item_layout.setSpacing(9)
            marker = QLabel(str(index + 1)); marker.setFixedSize(24, 24); marker.setAlignment(Qt.AlignCenter); marker.setObjectName("workflowMarker")
            text = QVBoxLayout(); name = QLabel(title); name.setObjectName("workflowTitle"); hint = QLabel(subtitle); hint.setObjectName("workflowHint"); hint.setWordWrap(True); text.addWidget(name); text.addWidget(hint)
            item_layout.addWidget(marker); item_layout.addLayout(text, 1); layout.addWidget(item); self.items.append((item, marker, name, hint))
        layout.addStretch(); footer = QLabel("Local • Source-aware\nOdoo 14 → 19"); footer.setStyleSheet("color:#A9B2C0;font-size:11px;"); layout.addWidget(footer); self.setCurrent(0)

    def setCurrent(self, index: int) -> None:  # noqa: N802
        for position, (item, marker, name, hint) in enumerate(self.items):
            if position < index: marker.setText("✓"); item.setProperty("workflowState", "completed")
            elif position == index: marker.setText(str(position + 1)); item.setProperty("workflowState", "current")
            else: marker.setText(str(position + 1)); item.setProperty("workflowState", "future")
            item.style().unpolish(item); item.style().polish(item)
