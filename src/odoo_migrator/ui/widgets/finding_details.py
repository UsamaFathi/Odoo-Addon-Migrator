from PySide6.QtWidgets import QLabel, QFormLayout, QGroupBox, QTextEdit, QVBoxLayout, QWidget


class FindingDetails(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields = {}
        form = QFormLayout()
        for name, label in (("severity", "Severity"), ("module", "Addon"), ("migration_step", "Migration step"),
                            ("rule_id", "Rule ID"), ("path", "File"), ("line", "Line"), ("object_name", "Object"),
                            ("source_state", "Source state"), ("target_state", "Target state")):
            value = QLabel("—"); value.setWordWrap(True); self.fields[name] = value; form.addRow(label + ":", value)
        self.problem = QTextEdit(); self.problem.setReadOnly(True); self.problem.setMaximumHeight(90)
        self.action = QTextEdit(); self.action.setReadOnly(True); self.action.setMaximumHeight(90)
        layout = QVBoxLayout(self); group = QGroupBox("Finding details"); group.setLayout(form); layout.addWidget(group)
        layout.addWidget(QLabel("Problem")); layout.addWidget(self.problem); layout.addWidget(QLabel("Suggested action")); layout.addWidget(self.action)

    def setFinding(self, finding) -> None:  # noqa: N802
        if not finding:
            for field in self.fields.values(): field.setText("—")
            self.problem.clear(); self.action.clear(); return
        for name, field in self.fields.items():
            value = getattr(finding, name, None)
            field.setText(getattr(value, "value", None) or str(value or "—"))
        self.problem.setPlainText(finding.message)
        self.action.setPlainText(finding.suggested_action or "Review the source and target behavior manually.")
