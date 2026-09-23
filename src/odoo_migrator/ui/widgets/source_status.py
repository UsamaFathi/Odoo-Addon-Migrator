from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from odoo_migrator.sources.registry import SourceMode, SourceSelection, source_spec
from odoo_migrator.ui.widgets.design_system import SurfaceCard, StatusBadge


class SourceVersionCard(SurfaceCard):
    localRequested = Signal(int)
    downloadRequested = Signal(int)
    forgetRequested = Signal(int)
    enterpriseRequested = Signal(int)
    enterpriseForgetRequested = Signal(int)

    def __init__(self, version: int, parent=None):
        super().__init__(parent); self.version = version; self.setMinimumWidth(165)
        layout = QVBoxLayout(self); layout.setContentsMargins(12, 10, 12, 10); layout.setSpacing(4)
        self.heading = QLabel(f"Odoo {version}"); self.heading.setObjectName("sectionTitle"); layout.addWidget(self.heading)
        self.status = StatusBadge("Source required", "badgeWarning"); layout.addWidget(self.status)
        self.mode = QLabel("Choose a source"); self.mode.setObjectName("muted"); self.mode.setWordWrap(True); layout.addWidget(self.mode)
        self.commit = QLabel(""); self.commit.setObjectName("muted"); self.commit.setWordWrap(True); layout.addWidget(self.commit)
        self.actions = QHBoxLayout(); self.local = QPushButton("Use local source"); self.local.setObjectName("secondary"); self.local.clicked.connect(lambda: self.localRequested.emit(self.version)); self.download = QPushButton("Use verified snapshot"); self.download.setObjectName("secondary"); self.download.clicked.connect(lambda: self.downloadRequested.emit(self.version)); self.change = QPushButton("Change folder"); self.change.setObjectName("secondary"); self.change.clicked.connect(lambda: self.localRequested.emit(self.version)); self.forget = QPushButton("Forget"); self.forget.setObjectName("secondary"); self.forget.clicked.connect(lambda: self.forgetRequested.emit(self.version)); self.actions.addWidget(self.local); self.actions.addWidget(self.download); self.actions.addWidget(self.change); self.actions.addWidget(self.forget); layout.addLayout(self.actions)
        self.enterprise_label = QLabel("Enterprise: not configured"); self.enterprise_label.setObjectName("muted"); self.enterprise_label.setWordWrap(True); layout.addWidget(self.enterprise_label)
        enterprise_actions = QHBoxLayout(); self.enterprise = QPushButton("Add Enterprise repo"); self.enterprise.setObjectName("secondary"); self.enterprise.clicked.connect(lambda: self.enterpriseRequested.emit(self.version)); self.enterprise_forget = QPushButton("Remove Enterprise"); self.enterprise_forget.setObjectName("secondary"); self.enterprise_forget.clicked.connect(lambda: self.enterpriseForgetRequested.emit(self.version)); enterprise_actions.addWidget(self.enterprise); enterprise_actions.addWidget(self.enterprise_forget); layout.addLayout(enterprise_actions)

    def set_snapshot(self, snapshot, selection: SourceSelection | None = None, enterprise_path: Path | None = None) -> None:
        expected = source_spec(self.version).verified_commit or "unknown"
        local = bool(selection and selection.mode is SourceMode.LOCAL_EXACT_SOURCE)
        verified = bool(snapshot and snapshot.source_mode is SourceMode.VERIFIED_SNAPSHOT and snapshot.expected_commit and snapshot.actual_commit == snapshot.expected_commit)
        self.local.setVisible(not local); self.download.setVisible(not local and not verified); self.change.setVisible(local); self.forget.setVisible(local)
        if local and snapshot:
            self.status.setText("Local source"); self.status.set_role("badgeSuccess"); self.mode.setText("Local Exact Source"); self.commit.setText(str(snapshot.path)); self.commit.setToolTip(str(snapshot.path))
            if snapshot.actual_commit: self.commit.setText(f"{snapshot.path}\nCommit: {snapshot.actual_commit[:12]}…")
            if snapshot.is_dirty: self.status.setText("Local source • Modified locally")
        elif verified:
            self.status.setText("Ready locally"); self.status.set_role("badgeSuccess"); self.mode.setText("Verified Snapshot"); self.commit.setText(snapshot.actual_commit[:12] + "…"); self.commit.setToolTip(snapshot.actual_commit or "")
        elif selection and selection.mode is SourceMode.VERIFIED_SNAPSHOT:
            self.status.setText("Download required"); self.status.set_role("badgeWarning"); self.mode.setText("Verified Snapshot"); self.commit.setText(expected[:12] + "…"); self.commit.setToolTip(expected)
        else:
            self.status.setText("Source required"); self.status.set_role("badgeWarning"); self.mode.setText("Choose local or verified"); self.commit.setText(expected[:12] + "…"); self.commit.setToolTip(expected)
        if enterprise_path:
            self.enterprise_label.setText(f"Enterprise: {enterprise_path}")
            self.enterprise_label.setToolTip(str(enterprise_path))
            self.enterprise.setText("Change Enterprise repo")
            self.enterprise_forget.setVisible(True)
        else:
            self.enterprise_label.setText("Enterprise: optional • repo or version folder")
            self.enterprise.setText("Add Enterprise repo")
            self.enterprise_forget.setVisible(False)


class SourceStatus(QWidget):
    localRequested = Signal(int)
    downloadRequested = Signal(int)
    forgetRequested = Signal(int)
    enterpriseRequested = Signal(int)
    enterpriseForgetRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent); self.cards: list[SourceVersionCard] = []
        self.label = QLabel("Select versions to check the local verified source cache."); self.label.setObjectName("muted"); self.label.setVisible(False)
        self.layout = QVBoxLayout(self); self.layout.setContentsMargins(0, 0, 0, 0); self.layout.setSpacing(7)
        title_row = QHBoxLayout(); title = QLabel("Official Odoo sources"); title.setObjectName("sectionTitle"); title_row.addWidget(title); title_row.addStretch(); title_row.addWidget(QLabel("Each version can use its own source.")); self.layout.addLayout(title_row)
        self.row = QHBoxLayout(); self.row.setSpacing(8); self.layout.addLayout(self.row); self.layout.addWidget(self.label)

    def set_versions(self, versions: list[int], snapshots=None, selections: dict[int, SourceSelection] | None = None,
                     enterprise_sources: dict[int, Path] | None = None) -> None:
        while self.row.count():
            item = self.row.takeAt(0); widget = item.widget()
            if widget: widget.deleteLater()
        self.cards = []; lines = []
        for version in versions:
            card = SourceVersionCard(version); card.localRequested.connect(self.localRequested); card.downloadRequested.connect(self.downloadRequested); card.forgetRequested.connect(self.forgetRequested); card.enterpriseRequested.connect(self.enterpriseRequested); card.enterpriseForgetRequested.connect(self.enterpriseForgetRequested)
            selection = (selections or {}).get(version); snapshot = (snapshots or {}).get(version) if snapshots else None; card.set_snapshot(snapshot, selection, (enterprise_sources or {}).get(version)); self.cards.append(card); self.row.addWidget(card); lines.append(f"Odoo {version}  •  {card.status.text()}")
        self.row.addStretch()
        details = []
        for card, line in zip(self.cards, lines): details.append(line + f"\n{card.mode.text()}\n{card.commit.text()}")
        self.label.setText("\n\n".join(details) if details else "No implemented target is available from this source version.")
