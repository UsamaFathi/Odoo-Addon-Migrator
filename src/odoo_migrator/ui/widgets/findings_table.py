from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QTableView, QVBoxLayout, QWidget

from odoo_migrator.ui.models.findings_model import FindingsModel


class FindingsTable(QWidget):
    findingSelected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = FindingsModel(self)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search findings…")
        self.severity = QComboBox(); self.severity.addItems(["All", "blocker", "review_required", "warning"])
        self.step = QComboBox(); self.step.addItem("All")
        self.addon = QComboBox(); self.addon.addItem("All")
        filters = QHBoxLayout(); filters.addWidget(self.search, 1); filters.addWidget(self.severity); filters.addWidget(self.step); filters.addWidget(self.addon)
        self.table = QTableView(); self.table.setModel(self.model); self.table.setSortingEnabled(True); self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows); self.table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(self); layout.addLayout(filters); layout.addWidget(self.table)
        self.search.textChanged.connect(lambda value: self.model.setFilter(search=value))
        self.severity.currentTextChanged.connect(lambda value: self.model.setFilter(severity=value))
        self.step.currentTextChanged.connect(lambda value: self.model.setFilter(step=value))
        self.addon.currentTextChanged.connect(lambda value: self.model.setFilter(addon=value))
        self.table.clicked.connect(lambda index: self.findingSelected.emit(self.model.finding(index.row())))

    def setFindings(self, findings) -> None:  # noqa: N802
        findings = list(findings)
        self.model.setFindings(findings)
        self.step.blockSignals(True); self.addon.blockSignals(True)
        self.step.clear(); self.step.addItem("All"); self.step.addItems(sorted({f.migration_step for f in findings if f.migration_step}))
        self.addon.clear(); self.addon.addItem("All"); self.addon.addItems(sorted({f.module for f in findings}))
        self.step.setCurrentText("All"); self.addon.setCurrentText("All")
        self.step.blockSignals(False); self.addon.blockSignals(False)

    def clearFilters(self) -> None:  # noqa: N802
        self.search.clear(); self.severity.setCurrentText("All"); self.step.setCurrentText("All"); self.addon.setCurrentText("All")
