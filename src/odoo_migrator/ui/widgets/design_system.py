from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


class SurfaceCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("surfaceCard")


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 4); layout.setSpacing(3)
        heading = QLabel(title); heading.setObjectName("pageTitle"); layout.addWidget(heading)
        if subtitle:
            label = QLabel(subtitle); label.setObjectName("subtitle"); label.setWordWrap(True); layout.addWidget(label)


class MetricCard(SurfaceCard):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(14, 12, 14, 12); layout.setSpacing(3)
        caption = QLabel(label.upper()); caption.setObjectName("muted"); layout.addWidget(caption)
        self.value = QLabel("0"); self.value.setStyleSheet("font-size: 22px; font-weight: 700; color: #101828;"); layout.addWidget(self.value)
        self.detail = QLabel(""); self.detail.setObjectName("muted"); layout.addWidget(self.detail)

    def set_value(self, value: object, detail: str = "") -> None:
        self.value.setText(str(value)); self.detail.setText(detail)


class StatusBadge(QLabel):
    def __init__(self, text: str = "", role: str = "badgeInfo", parent=None):
        super().__init__(text, parent); self.set_role(role)

    def set_role(self, role: str) -> None:
        self.setObjectName(role)
        self.style().unpolish(self); self.style().polish(self)


class EmptyState(QWidget):
    def __init__(self, title: str, message: str, action: QPushButton | None = None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 28, 24, 28); layout.setSpacing(7)
        heading = QLabel(title); heading.setObjectName("sectionTitle"); layout.addWidget(heading)
        body = QLabel(message); body.setObjectName("muted"); body.setWordWrap(True); layout.addWidget(body)
        if action: layout.addWidget(action)


class PrimaryButton(QPushButton):
    pass


class SecondaryButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent); self.setObjectName("secondary")
