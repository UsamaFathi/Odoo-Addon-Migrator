from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QFormLayout, QGroupBox, QPushButton, QTextEdit, QVBoxLayout, QWidget


class FindingDetails(QWidget):
    openLocation = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields = {}
        self._finding = None
        self._project_root: Path | None = None
        form = QFormLayout()
        for name, label in (("severity", "Severity"), ("module", "Addon"), ("migration_step", "Migration step"),
                            ("rule_id", "Rule ID"), ("path", "File"), ("line", "Line"), ("object_name", "Object"),
                            ("source_state", "Source state"), ("target_state", "Target state")):
            value = QLabel("—"); value.setWordWrap(True); self.fields[name] = value; form.addRow(label + ":", value)
        self.problem = QTextEdit(); self.problem.setReadOnly(True); self.problem.setMaximumHeight(90)
        self.action = QTextEdit(); self.action.setReadOnly(True); self.action.setMaximumHeight(90)
        self.open_button = QPushButton("Open File Location")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(lambda: self.openLocation.emit(self._safe_path()))
        layout = QVBoxLayout(self); group = QGroupBox("Finding details"); group.setLayout(form); layout.addWidget(group)
        layout.addWidget(QLabel("Problem")); layout.addWidget(self.problem); layout.addWidget(QLabel("Suggested action")); layout.addWidget(self.action)
        layout.addWidget(self.open_button)

    def set_project_root(self, root: Path | None) -> None:
        self._project_root = root.resolve() if root else None
        self.open_button.setEnabled(self._safe_path() is not None)

    def _safe_path(self) -> Path | None:
        if not self._finding or not self._finding.path or not self._project_root:
            return None
        raw = Path(self._finding.path)
        candidates = []
        if raw.is_absolute():
            candidates.append(raw)
        else:
            if self._finding.module:
                candidates.append(self._project_root / self._finding.module / raw)
            candidates.append(self._project_root / raw)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_file() and resolved.is_relative_to(self._project_root):
                return resolved
        return None

    def setFinding(self, finding) -> None:  # noqa: N802
        self._finding = finding
        if not finding:
            for field in self.fields.values(): field.setText("—")
            self.problem.clear(); self.action.clear(); self.open_button.setEnabled(False); return
        for name, field in self.fields.items():
            value = getattr(finding, name, None)
            field.setText(getattr(value, "value", None) or str(value or "—"))
        self.problem.setPlainText(finding.message)
        self.action.setPlainText(finding.suggested_action or "Review the source and target behavior manually.")
        self.open_button.setEnabled(self._safe_path() is not None)
