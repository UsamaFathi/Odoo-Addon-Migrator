from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout


class SourceStatus(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Odoo source status", parent)
        self.label = QLabel("Sources will be prepared when analysis starts.")
        self.label.setWordWrap(True)
        layout = QVBoxLayout(self); layout.addWidget(self.label)

    def set_versions(self, versions: list[int], snapshots=None) -> None:
        if snapshots:
            lines = [f"Odoo {v}  •  {snapshots[v].source_mode.value}  •  {snapshots[v].actual_commit[:12]}" for v in versions]
        else:
            lines = [f"Odoo {v}  •  source required" for v in versions]
        self.label.setText("\n".join(lines))
