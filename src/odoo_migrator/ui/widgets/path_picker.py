from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget


class PathPicker(QWidget):
    pathChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pathPicker")
        self.empty_state = QWidget()
        self.empty_state.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        empty_layout = QHBoxLayout(self.empty_state); empty_layout.setContentsMargins(16, 12, 16, 12); empty_layout.setSpacing(16)
        empty_copy = QVBoxLayout(); empty_copy.setContentsMargins(0, 0, 0, 0); empty_copy.setSpacing(2)
        empty_title = QLabel("Select your custom_addons folder"); empty_title.setObjectName("sectionTitle"); empty_copy.addWidget(empty_title)
        empty_hint = QLabel("Drag a folder here or browse to choose one. Your original files will never be modified."); empty_hint.setObjectName("muted"); empty_hint.setWordWrap(True); empty_copy.addWidget(empty_hint)
        empty_layout.addLayout(empty_copy, 1)
        self.empty_browse = QPushButton("Browse folders"); self.empty_browse.clicked.connect(self._browse); empty_layout.addWidget(self.empty_browse, 0, Qt.AlignmentFlag.AlignVCenter)
        self.edit = QLineEdit(); self.edit.setPlaceholderText("Selected custom_addons folder")
        self.edit.setToolTip("The full selected folder path")
        self.edit.textChanged.connect(self._path_text_changed)
        browse = QPushButton("Browse…"); browse.setObjectName("secondary"); browse.clicked.connect(self._browse)
        clear = QPushButton("Clear"); clear.setObjectName("secondary"); clear.clicked.connect(lambda: self.setPath(""))
        self.compact = QWidget(); self.compact.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed); compact_layout = QHBoxLayout(self.compact); compact_layout.setContentsMargins(0, 0, 0, 0)
        compact_layout.addWidget(self.edit, 1); compact_layout.addWidget(browse); compact_layout.addWidget(clear)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.addWidget(self.empty_state); root.addWidget(self.compact)
        self._update_mode(""); self.setAcceptDrops(True)

    def path(self) -> Path:
        return Path(self.edit.text().strip())

    def setPath(self, path: str | Path) -> None:
        self.edit.setText(str(path))

    def _update_mode(self, value: str) -> None:
        has_path = bool(value.strip()); self.empty_state.setVisible(not has_path); self.compact.setVisible(has_path)

    def _path_text_changed(self, value: str) -> None:
        self._update_mode(value); self.pathChanged.emit(value)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.setPath(url.toLocalFile()); event.acceptProposedAction(); return

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select custom addons folder", str(self.path()) if self.path().is_dir() else "")
        if selected: self.setPath(selected)
