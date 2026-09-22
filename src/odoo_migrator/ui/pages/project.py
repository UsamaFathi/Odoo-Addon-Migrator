from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from odoo_migrator.ui.models.application_state import suggested_output_path
from odoo_migrator.ui.widgets.path_picker import PathPicker
from odoo_migrator.ui.widgets.source_status import SourceStatus


class ProjectPage(QWidget):
    analyzeRequested = Signal()
    sourceChanged = Signal(int)
    targetChanged = Signal(int)
    outputChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path_picker = PathPicker(); self.path_picker.pathChanged.connect(self._path_changed)
        self.source = QComboBox(); self.target = QComboBox()
        self.source.currentTextChanged.connect(lambda value: value and self.sourceChanged.emit(int(value)))
        self.target.currentTextChanged.connect(lambda value: value and self.targetChanged.emit(int(value)))
        self.output = QLineEdit(); self.output.setPlaceholderText("Suggested migrated output folder"); self.output.textChanged.connect(self.outputChanged)
        self.summary = QLabel("Select a folder to scan its Odoo addons."); self.summary.setObjectName("muted"); self.summary.setWordWrap(True)
        self.warning = QLabel(); self.warning.setWordWrap(True); self.warning.hide()
        self.sources = SourceStatus()
        self.modules = QTableWidget(0, 8); self.modules.setHorizontalHeaderLabels(("Addon", "Version", "Dependencies", "Python", "XML", "JS", "Security", "Status"))
        self.modules.setAlternatingRowColors(True); self.modules.horizontalHeader().setStretchLastSection(True)
        self.analyze_button = QPushButton("Analyze Project"); self.analyze_button.clicked.connect(self.analyzeRequested)
        form = QFormLayout(); form.addRow("Custom addons folder", self.path_picker); form.addRow("Source version", self.source); form.addRow("Target version", self.target); form.addRow("Output folder", self.output)
        box = QGroupBox("Project setup"); box.setLayout(form)
        layout = QVBoxLayout(self); layout.addWidget(QLabel("Project", objectName="sectionTitle")); layout.addWidget(QLabel("Select a custom_addons folder. The application scans it locally and never changes it.")); layout.addWidget(box); layout.addWidget(self.warning); layout.addWidget(self.summary); layout.addWidget(self.sources); layout.addWidget(QLabel("Detected addons", objectName="sectionTitle")); layout.addWidget(self.modules, 1); layout.addWidget(self.analyze_button)

    def set_source_versions(self, versions: list[int], selected: int | None = None) -> None:
        self.source.blockSignals(True); self.source.clear(); self.source.addItems([str(v) for v in versions])
        if selected is not None and str(selected) in [self.source.itemText(i) for i in range(self.source.count())]: self.source.setCurrentText(str(selected))
        self.source.blockSignals(False)

    def set_targets(self, targets: tuple[int, ...], selected: int | None = None) -> None:
        self.target.blockSignals(True); self.target.clear(); self.target.addItems([str(v) for v in targets])
        if selected is not None and str(selected) in [self.target.itemText(i) for i in range(self.target.count())]: self.target.setCurrentText(str(selected))
        self.target.blockSignals(False)
        if self.target.currentText(): self.targetChanged.emit(int(self.target.currentText()))

    def selected_source(self) -> int | None:
        return int(self.source.currentText()) if self.source.currentText() else None

    def selected_target(self) -> int | None:
        return int(self.target.currentText()) if self.target.currentText() else None

    def selected_output(self) -> Path:
        return Path(self.output.text().strip())

    def set_scan(self, scan) -> None:
        stats = scan.file_statistics
        self.summary.setText(f"{scan.module_count} addons detected  •  Python: {stats['python']}  •  XML: {stats['xml']}  •  JavaScript: {stats['javascript']}  •  CSV/security: {stats['csv']}  •  Other: {stats['other']}")
        self.modules.setRowCount(0)
        for name, module in sorted(scan.index.modules.items()):
            row = self.modules.rowCount(); self.modules.insertRow(row)
            values = (name, str(module.manifest.get("version", "unknown")), ", ".join(module.depends), str(module.files.get("python", 0)), str(module.files.get("xml", 0)), str(module.files.get("javascript", 0)), str(module.files.get("csv", 0)), "Detected")
            for column, value in enumerate(values): self.modules.setItem(row, column, QTableWidgetItem(value))
        versions = scan.version_counts
        if scan.has_version_conflict:
            self._set_status("Mixed addon versions detected: " + ", ".join(f"Odoo {v}: {count}" for v, count in sorted(versions.items())) + ". Select the intended source version explicitly.", "badgeWarning")
        elif scan.detected_version:
            self._set_status(f"Detected source: Odoo {scan.detected_version} • {versions[scan.detected_version]} addon(s) agree.", "badgeSuccess")
        else:
            self._set_status("Source version could not be detected from addon manifests. Select it manually.", "badgeWarning")

    def suggest_output(self, target: int) -> None:
        root = self.path_picker.path()
        if root: self.output.setText(str(suggested_output_path(root, target)))

    def set_busy(self, busy: bool) -> None:
        self.analyze_button.setEnabled(not busy)

    def set_source_requirements(self, source: int, target: int, snapshots=None) -> None:
        self.sources.set_versions(list(range(source, target + 1)), snapshots)

    def set_error(self, message: str) -> None:
        self._set_status(message, "badgeDanger")

    def _set_status(self, message: str, role: str) -> None:
        self.warning.setObjectName(role); self.warning.setText(message); self.warning.show()
        self.warning.style().unpolish(self.warning); self.warning.style().polish(self.warning)

    def _path_changed(self, value: str) -> None:
        self.warning.hide(); self.summary.setText("Scanning selected folder…" if value else "Select a folder to scan its Odoo addons.")
