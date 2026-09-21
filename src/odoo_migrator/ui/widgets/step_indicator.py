from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class StepIndicator(QWidget):
    STEPS = (("1", "Project"), ("2", "Analyze"), ("3", "Review"), ("4", "Migrate"), ("5", "Validate"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = []
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        for number, text in self.STEPS:
            label = QLabel(f"{number}  {text}")
            label.setObjectName("muted")
            self.labels.append(label); layout.addWidget(label)

    def setCurrent(self, index: int) -> None:  # noqa: N802 - Qt-facing API
        for position, label in enumerate(self.labels):
            label.setStyleSheet("font-weight:700;color:#315efb" if position == index else "")
