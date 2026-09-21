from __future__ import annotations

import os
import sys
from pathlib import Path

from odoo_migrator.analysis.project import scan_custom_addons
from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.core.planner import build_plan
from odoo_migrator.migrations.engine import MigrationEngine


def main() -> None:
    try:
        from PySide6.QtCore import QObject, QThread, Signal, Qt
        from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QGridLayout,
            QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton,
            QProgressBar, QTextEdit, QVBoxLayout, QWidget)
    except ImportError as exc:
        raise SystemExit('Desktop dependency missing. Install with: pip install -e ".[desktop]"') from exc

    class Worker(QObject):
        done = Signal(object)
        failed = Signal(str)
        progress = Signal(str)

        def __init__(self, operation, *args):
            super().__init__(); self.operation = operation; self.args = args

        def run(self):
            try: self.done.emit(self.operation(*self.args))
            except Exception as exc: self.failed.emit(str(exc))

    class DropLineEdit(QLineEdit):
        pathDropped = Signal(str)
        def __init__(self):
            super().__init__(); self.setAcceptDrops(True)
        def dragEnterEvent(self, event):
            if event.mimeData().hasUrls(): event.acceptProposedAction()
        def dropEvent(self, event):
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile(): self.pathDropped.emit(urls[0].toLocalFile())

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__(); self.setWindowTitle("Odoo Addon Migrator"); self.resize(980, 720)
            self.scan = None; self.analysis = None; self.thread = None; self.worker = None; self.busy = False
            self.input_edit = DropLineEdit(); self.output_edit = QLineEdit()
            self.source_box = QComboBox(); self.source_box.addItems([str(v) for v in range(14, 20)])
            self.target_box = QComboBox(); self.module_list = QListWidget()
            self.status = QLabel("Choose a custom addons folder to begin."); self.stats = QLabel("No folder scanned")
            self.path_label = QLabel("—"); self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.hide()
            self.details = QTextEdit(); self.details.setReadOnly(True)
            self.analyze_btn = QPushButton("Analyze Project"); self.migrate_btn = QPushButton("Start Migration")
            self.open_btn = QPushButton("Open Output Folder"); self.open_btn.setEnabled(False)
            self._build(); self._style(); self._refresh_targets()
            self.input_edit.textChanged.connect(self._folder_changed); self.input_edit.pathDropped.connect(self._set_input)
            self.source_box.currentTextChanged.connect(self._refresh_targets); self.target_box.currentTextChanged.connect(self._refresh_path)
            self.analyze_btn.clicked.connect(self._analyze); self.migrate_btn.clicked.connect(self._migrate); self.open_btn.clicked.connect(self._open_output)

        def _build(self):
            def row(label, edit, browse=False):
                box = QHBoxLayout(); box.addWidget(QLabel(label)); box.addWidget(edit, 1)
                if browse:
                    button = QPushButton("Browse"); button.clicked.connect(lambda: self._browse(edit)); box.addWidget(button)
                return box
            root = QVBoxLayout(); root.setContentsMargins(28, 24, 28, 24)
            title = QLabel("Odoo Addon Migrator"); title.setObjectName("title"); root.addWidget(title)
            root.addWidget(QLabel("Upgrade custom Odoo addons safely and locally."))
            root.addSpacing(14); root.addLayout(row("Custom addons folder", self.input_edit, True))
            root.addWidget(self.stats); root.addWidget(self.status)
            grid = QGridLayout(); grid.addWidget(QLabel("Source version"), 0, 0); grid.addWidget(self.source_box, 0, 1)
            grid.addWidget(QLabel("Target version"), 0, 2); grid.addWidget(self.target_box, 0, 3)
            grid.addWidget(QLabel("Migration path"), 1, 0); grid.addWidget(self.path_label, 1, 1, 1, 3)
            grid.addWidget(QLabel("Output folder"), 2, 0); grid.addWidget(self.output_edit, 2, 1, 1, 3); root.addLayout(grid)
            root.addWidget(QLabel("Detected addons")); root.addWidget(self.module_list, 1)
            actions = QHBoxLayout(); actions.addWidget(self.analyze_btn); actions.addWidget(self.migrate_btn); actions.addWidget(self.open_btn); root.addLayout(actions)
            root.addWidget(self.progress); root.addWidget(QLabel("Analysis and migration details")); root.addWidget(self.details, 1)
            frame = QFrame(); frame.setLayout(root); self.setCentralWidget(frame)

        def _style(self):
            self.setStyleSheet("""QMainWindow{background:#f4f6f8} QFrame{background:#fff} QLabel{color:#344054;font-size:13px} #title{font-size:26px;font-weight:700;color:#182230} QLineEdit,QComboBox,QListWidget,QTextEdit{border:1px solid #d0d5dd;border-radius:6px;padding:7px;background:#fff} QPushButton{padding:8px 14px;border-radius:6px;background:#2563eb;color:#fff;font-weight:600} QPushButton:disabled{background:#98a2b3} QProgressBar{height:8px}""")

        def _browse(self, edit):
            path = QFileDialog.getExistingDirectory(self, "Select custom addons folder")
            if path: edit.setText(path)
        def _set_input(self, path): self.input_edit.setText(path)
        def _folder_changed(self):
            self.analysis = None; self.migrate_btn.setEnabled(False)
            path = Path(self.input_edit.text())
            if not path.is_dir(): self.status.setText("Select a valid folder containing Odoo addons."); return
            self.status.setText("Scanning addons…"); self._start(scan_custom_addons, path, self._scan_done)
        def _scan_done(self, result):
            self.scan = result; self.module_list.clear(); self.module_list.addItems(sorted(result.index.modules))
            files = sum(sum(m.files.values()) for m in result.index.modules.values())
            self.stats.setText(f"{result.module_count} addons detected  •  {files} source files")
            versions = {}
            for module in result.index.modules.values():
                value = str(module.manifest.get("version", "")); prefix = value.split(".")[0]
                if prefix.isdigit() and 14 <= int(prefix) <= 19: versions[int(prefix)] = versions.get(int(prefix), 0) + 1
            if len(versions) == 1: self.source_box.setCurrentText(str(next(iter(versions))))
            elif len(versions) > 1: self.status.setText("Version conflict detected; please select the source version.")
            else: self.status.setText("Addons detected. Select source and target versions.")
            self._refresh_path()
        def _refresh_targets(self):
            self.analysis = None; self.migrate_btn.setEnabled(False)
            source = int(self.source_box.currentText()); current = self.target_box.currentText(); self.target_box.clear(); self.target_box.addItems([str(v) for v in range(source + 1, 20)])
            if current in [self.target_box.itemText(i) for i in range(self.target_box.count())]: self.target_box.setCurrentText(current)
            self._refresh_path()
        def _refresh_path(self):
            self.analysis = None; self.migrate_btn.setEnabled(False)
            if not self.target_box.currentText(): return
            plan = build_plan(int(self.source_box.currentText()), int(self.target_box.currentText())); self.path_label.setText(plan.path_label)
            if self.input_edit.text(): self.output_edit.setText(str(Path(self.input_edit.text()).parent / f"{Path(self.input_edit.text()).name}_{plan.target}"))
        def _analyze(self):
            if not self.scan: return self._error("Scan a valid addons folder first.")
            self._start(AnalysisService().analyze, Path(self.input_edit.text()), int(self.source_box.currentText()), int(self.target_box.currentText()), callback=self._analysis_done)
        def _analysis_done(self, result):
            if (str(Path(self.input_edit.text()).resolve()), int(self.source_box.currentText()), int(self.target_box.currentText())) != (str(result.scan.root), result.plan.source, result.plan.target):
                return
            self.analysis = result
            counts = {level: sum(1 for item in result.findings if item.severity.value == level) for level in ("blocker", "warning", "review_required")}
            blocked = counts["blocker"] > 0
            self.migrate_btn.setEnabled(not blocked)
            suffix = " • Migration blocked until blocking issues are resolved." if blocked else ""
            self.status.setText(f"Analysis complete • {counts['blocker']} blockers • {counts['warning']} warnings • {counts['review_required']} review items{suffix}")
            self.details.setPlainText("\n".join(f"{item.severity.value.upper()}: {item.module} — {item.message}" for item in result.findings) or "No compatibility findings.")
        def _migrate(self):
            if not self.analysis: return self._error("Analyze the project before migration.")
            self._start(MigrationService().migrate, Path(self.input_edit.text()), Path(self.output_edit.text()), self.analysis, callback=self._migration_done)
        def _migration_done(self, result):
            self.status.setText(f"Migration completed: {len(result.changes)} change(s)"); self.open_btn.setEnabled(True); self.details.setPlainText(str(result.metadata_path))
        def _start(self, operation, *args, callback=None):
            if self.busy: return self._error("Another operation is still running.")
            self.busy = True; self.progress.show(); self.analyze_btn.setEnabled(False); self.migrate_btn.setEnabled(False)
            self.thread = QThread(self); self.worker = Worker(operation, *args); self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.worker.done.connect(callback or (lambda _: None)); self.worker.failed.connect(self._error); self.worker.done.connect(self._finish); self.worker.failed.connect(self._finish); self.thread.finished.connect(self.worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater); self.thread.start()
        def _finish(self, *_):
            self.progress.hide(); self.analyze_btn.setEnabled(True); self.busy = False
            self.migrate_btn.setEnabled(bool(self.analysis and not self.analysis.blockers))
            thread = self.thread
            if thread: thread.quit()
        def _error(self, message): QMessageBox.critical(self, "Odoo Addon Migrator", message); self.status.setText("Operation failed. See the error dialog for details.")
        def _open_output(self): os.startfile(self.output_edit.text())

    app = QApplication(sys.argv); window = MainWindow(); window.show(); sys.exit(app.exec())


if __name__ == "__main__": main()
