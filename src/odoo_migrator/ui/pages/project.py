from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QAbstractScrollArea, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton, QSizePolicy, QTableView, QVBoxLayout, QWidget

from odoo_migrator.ui.models.addons_model import AddonsModel
from odoo_migrator.ui.models.application_state import suggested_output_path
from odoo_migrator.ui.widgets.design_system import MetricCard, SectionHeader, StatusBadge, SurfaceCard
from odoo_migrator.ui.widgets.path_picker import PathPicker
from odoo_migrator.ui.widgets.source_status import SourceStatus
from odoo_migrator.sources.registry import SourceSelection


class ScrollSafeComboBox(QComboBox):
    """Let the containing page handle wheel scrolling instead of changing versions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.installEventFilter(self)

    def _scroll_page(self, event) -> bool:
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if isinstance(parent, QAbstractScrollArea):
            bar = parent.verticalScrollBar()
            pixel_delta = event.pixelDelta().y()
            step = -pixel_delta if pixel_delta else -event.angleDelta().y() / 120 * bar.singleStep()
            bar.setValue(bar.value() + int(step))
            event.accept()
            return True
        return False

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self and event.type() == QEvent.Type.Wheel and self._scroll_page(event):
            return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._scroll_page(event):
            return
        event.ignore()


class ProjectPage(QWidget):
    analyzeRequested = Signal()
    sourceChanged = Signal(int)
    targetChanged = Signal(int)
    outputChanged = Signal(str)
    localSourceRequested = Signal(int)
    downloadSourceRequested = Signal(int)
    forgetSourceRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path_picker = PathPicker(); self.path_picker.pathChanged.connect(self._path_changed)
        self.browse_button = QPushButton("Browse…"); self.browse_button.setObjectName("secondary"); self.browse_button.clicked.connect(self.path_picker.browse)
        self.source = ScrollSafeComboBox(); self.source.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.target = ScrollSafeComboBox(); self.target.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.source.setPlaceholderText("Detect after scan"); self.target.setPlaceholderText("Choose target")
        self.source.currentTextChanged.connect(lambda value: value and self.sourceChanged.emit(int(value)))
        self.target.currentTextChanged.connect(lambda value: value and self.targetChanged.emit(int(value)))
        self.output = QLineEdit(); self.output.setPlaceholderText("Suggested migrated output folder"); self.output.textChanged.connect(self.outputChanged)
        self.warning = QLabel(); self.warning.setWordWrap(True); self.warning.hide()
        self.summary = QLabel("Choose your custom_addons folder to begin."); self.summary.setObjectName("muted"); self.summary.setWordWrap(True)
        self.detection = StatusBadge("Source not detected", "badgeInfo")
        self.sources = SourceStatus()
        self.sources.localRequested.connect(self.localSourceRequested)
        self.sources.downloadRequested.connect(self.downloadSourceRequested)
        self.sources.forgetRequested.connect(self.forgetSourceRequested)
        self.metrics = []
        self.model = AddonsModel(self); self.modules = QTableView(); self.modules.setModel(self.model); self.modules.setSortingEnabled(True); self.modules.setAlternatingRowColors(True)
        self.modules.setSelectionBehavior(QTableView.SelectRows); self.modules.verticalHeader().setDefaultSectionSize(36); self.modules.horizontalHeader().setStretchLastSection(True)
        self.module_search = QLineEdit(); self.module_search.setPlaceholderText("Filter detected addons…"); self.module_search.textChanged.connect(self._filter_modules)
        self.analyze_button = QPushButton("Analyze project  →"); self.analyze_button.clicked.connect(self.analyzeRequested); self.analyze_button.setEnabled(False)
        self._build()
        self._set_controls_enabled(False)

    def _build(self) -> None:
        main = QVBoxLayout(self); main.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize); main.setContentsMargins(28, 24, 28, 24); main.setSpacing(14)
        main.addWidget(SectionHeader("Project", "Select the custom addons you want to migrate. Your original files will never be modified."))
        setup = SurfaceCard(); setup.setObjectName("projectSetupCard"); setup.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum); self.setup_card = setup
        setup_layout = QGridLayout(setup); setup_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize); setup_layout.setContentsMargins(20, 18, 20, 18); setup_layout.setHorizontalSpacing(18); setup_layout.setVerticalSpacing(12)
        self.path_label = self._field_label("CUSTOM ADDONS FOLDER")
        self.source_label = self._field_label("SOURCE VERSION")
        self.target_label = self._field_label("TARGET VERSION")
        self.output_label = self._field_label("OUTPUT FOLDER")
        setup_layout.addWidget(self.path_label, 0, 0, 1, 3)
        setup_layout.addWidget(self.path_picker, 1, 0, 1, 2)
        setup_layout.addWidget(self.browse_button, 1, 2)
        setup_layout.addWidget(self.source_label, 2, 0)
        setup_layout.addWidget(self.target_label, 2, 1)
        setup_layout.addWidget(self.source, 3, 0)
        setup_layout.addWidget(self.target, 3, 1)
        setup_layout.addWidget(self.output_label, 4, 0, 1, 3)
        setup_layout.addWidget(self.output, 5, 0, 1, 3)
        setup_layout.setColumnStretch(0, 1); setup_layout.setColumnStretch(1, 1); setup_layout.setColumnStretch(2, 0)
        main.addWidget(setup, 0); main.addWidget(self.warning, 0); main.addWidget(self.detection, 0)
        metric_row = QHBoxLayout(); metric_row.setSpacing(8)
        for label in ("Addons", "Python", "XML", "JavaScript", "Security"):
            card = MetricCard(label); self.metrics.append(card); metric_row.addWidget(card)
        main.addLayout(metric_row, 0)
        main.addWidget(self.sources, 0)
        table_header = QHBoxLayout(); title = QLabel("Detected addons"); title.setObjectName("sectionTitle"); table_header.addWidget(title); table_header.addStretch(); table_header.addWidget(self.module_search); main.addLayout(table_header, 0)
        main.addWidget(self.modules, 1)
        action_bar = QHBoxLayout(); action_bar.addStretch(); action_bar.addWidget(self.analyze_button); main.addLayout(action_bar, 0)

    @staticmethod
    def _field_label(text: str) -> QLabel:
        caption = QLabel(text); caption.setObjectName("fieldLabel"); return caption

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.source.setEnabled(enabled); self.target.setEnabled(enabled); self.output.setEnabled(enabled)
        self.analyze_button.setEnabled(enabled and bool(self.selected_target()))

    def set_source_versions(self, versions: list[int], selected: int | None = None) -> None:
        self.source.blockSignals(True); self.source.clear(); self.source.addItems([str(v) for v in versions])
        if selected is not None and str(selected) in [self.source.itemText(i) for i in range(self.source.count())]: self.source.setCurrentText(str(selected))
        self.source.blockSignals(False)

    def set_targets(self, targets: tuple[int, ...], selected: int | None = None) -> None:
        self.target.blockSignals(True); self.target.clear(); self.target.addItems([str(v) for v in targets])
        if selected is not None and str(selected) in [self.target.itemText(i) for i in range(self.target.count())]: self.target.setCurrentText(str(selected))
        self.target.blockSignals(False)
        if self.target.currentText(): self.targetChanged.emit(int(self.target.currentText()))
        self.analyze_button.setEnabled(self.path_picker.path().is_dir() and bool(self.target.currentText()))

    def selected_source(self) -> int | None:
        return int(self.source.currentText()) if self.source.currentText() else None

    def selected_target(self) -> int | None:
        return int(self.target.currentText()) if self.target.currentText() else None

    def selected_output(self) -> Path:
        return Path(self.output.text().strip())

    def set_scan(self, scan) -> None:
        stats = scan.file_statistics; values = (scan.module_count, stats["python"], stats["xml"], stats["javascript"], stats["csv"])
        for card, value in zip(self.metrics, values): card.set_value(value, "addons" if card is self.metrics[0] else "files")
        self.model.set_scan(scan); self._set_controls_enabled(True)
        versions = scan.version_counts
        if scan.has_version_conflict:
            text = "Mixed addon versions"; detail = "  •  ".join(f"Odoo {v}: {count} addons" for v, count in sorted(versions.items())); self._set_status(f"{text}\n{detail}", "badgeWarning")
        elif scan.detected_version:
            self._set_status(f"✓ Odoo {scan.detected_version} detected\n{versions[scan.detected_version]} of {scan.module_count} addon manifests agree", "badgeSuccess")
        else:
            self._set_status("? Source not detected\nSelect the source version manually.", "badgeWarning")
        self.summary.setText(f"{scan.module_count} addons detected")

    def suggest_output(self, target: int) -> None:
        root = self.path_picker.path()
        if root: self.output.setText(str(suggested_output_path(root, target)))

    def set_busy(self, busy: bool) -> None:
        self.analyze_button.setEnabled(not busy and bool(self.selected_target()) and self.state_ready())
        self.path_picker.setEnabled(not busy)

    def state_ready(self) -> bool:
        return self.path_picker.path().is_dir()

    def set_source_requirements(self, source: int, target: int, snapshots=None, selections: dict[int, SourceSelection] | None = None) -> None:
        self.sources.set_versions(list(range(source, target + 1)), snapshots, selections)

    def set_error(self, message: str) -> None:
        self._set_status(message, "badgeDanger")

    def clear_project(self) -> None:
        self.path_picker.setPath(""); self.source.clear(); self.target.clear(); self.output.clear(); self.model.clear()
        self.summary.setText("Choose your custom_addons folder to begin."); self._set_status("Source not detected", "badgeInfo"); self._set_controls_enabled(False)

    def _set_status(self, message: str, role: str) -> None:
        first, _, second = message.partition("\n"); self.detection.setText(first); self.detection.set_role(role); self.detection.setToolTip(second)
        self.warning.setText(message); self.warning.setObjectName(role); self.warning.setVisible(role == "badgeDanger"); self.warning.style().unpolish(self.warning); self.warning.style().polish(self.warning)

    def _path_changed(self, value: str) -> None:
        self.warning.hide(); self.detection.setText("Scanning project…" if value else "Source not detected"); self.detection.set_role("badgeInfo")
        self.summary.setText("Scanning selected folder…" if value else "Choose your custom_addons folder to begin.")

    def _filter_modules(self, value: str) -> None:
        needle = value.casefold(); self.modules.setRowHidden
        for row in range(self.model.rowCount()):
            self.modules.setRowHidden(row, bool(needle) and needle not in " ".join(str(self.model.data(self.model.index(row, column)) or "") for column in range(self.model.columnCount())).casefold())
