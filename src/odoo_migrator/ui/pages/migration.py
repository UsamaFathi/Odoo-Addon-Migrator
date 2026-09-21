from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class MigrationPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.stage = QLabel("Preparing migration…"); self.stage.setObjectName("sectionTitle")
        self.destination = QLabel(); self.destination.setWordWrap(True)
        self.progress = QProgressBar(); self.progress.setRange(0, 100)
        layout = QVBoxLayout(self); layout.addWidget(QLabel("Migration", objectName="sectionTitle")); layout.addWidget(self.stage); layout.addWidget(self.destination); layout.addWidget(self.progress); layout.addStretch()

    def set_destination(self, path) -> None:
        self.destination.setText(f"Output: {path}")

    def set_progress(self, stage: str, percent: int) -> None:
        self.stage.setText(stage); self.progress.setValue(percent)

    def set_busy(self, busy: bool) -> None:
        self.progress.setEnabled(busy)
