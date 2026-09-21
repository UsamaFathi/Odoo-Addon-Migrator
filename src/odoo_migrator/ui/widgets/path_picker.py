from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QWidget


class PathPicker(QWidget):
    pathChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Select a custom_addons folder or drop it here")
        self.edit.textChanged.connect(self.pathChanged)
        browse = QPushButton("Browse…")
        browse.setObjectName("secondary")
        browse.clicked.connect(self._browse)
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1); layout.addWidget(browse)
        self.setAcceptDrops(True)

    def path(self) -> Path:
        return Path(self.edit.text().strip())

    def setPath(self, path: str | Path) -> None:
        self.edit.setText(str(path))

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.setPath(url.toLocalFile())
                event.acceptProposedAction()
                return

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select custom addons folder", str(self.path()) if self.path().is_dir() else "")
        if selected:
            self.setPath(selected)
