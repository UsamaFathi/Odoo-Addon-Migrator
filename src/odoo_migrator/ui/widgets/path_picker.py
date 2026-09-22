from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QLineEdit


class PathPicker(QLineEdit):
    """Permanent project-path field with native browsing and folder drop support."""

    pathChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.edit = self  # Compatibility for existing callers that access the editable field.
        self.setObjectName("projectPathField")
        self.setPlaceholderText("Select your custom_addons folder")
        self.setToolTip("Select or drag the folder containing your custom Odoo addons")
        self.setClearButtonEnabled(True)
        self.setAcceptDrops(True)
        self.textChanged.connect(self.pathChanged.emit)

    def path(self) -> Path:
        return Path(self.text().strip())

    def setPath(self, path: str | Path) -> None:
        self.setText(str(path))

    def browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select custom addons folder",
            str(self.path()) if self.path().is_dir() else "",
        )
        if selected:
            self.setPath(selected)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.setPath(url.toLocalFile())
                event.acceptProposedAction()
                return
