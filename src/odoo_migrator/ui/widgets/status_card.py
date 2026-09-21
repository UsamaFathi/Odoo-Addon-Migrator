from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class StatusCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        self.title = QLabel(title); self.title.setObjectName("muted")
        self.value = QLabel("0"); self.value.setStyleSheet("font-size:22px;font-weight:700;color:#14213d")
        layout.addWidget(self.title); layout.addWidget(self.value)

    def setValue(self, value: object) -> None:  # noqa: N802 - Qt-facing API
        self.value.setText(str(value))
