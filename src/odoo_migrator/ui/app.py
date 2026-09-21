from __future__ import annotations

import sys
from pathlib import Path

from odoo_migrator.core.planner import build_plan
from odoo_migrator.sources.manager import SourceManager, SourceManagerError
from odoo_migrator.migrations.engine import MigrationEngine


def main() -> None:
    try:
        from PySide6.QtCore import QThread, Signal
        from PySide6.QtWidgets import (
            QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
            QLineEdit, QMainWindow, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget
        )
    except ImportError as exc:
        raise SystemExit('Desktop dependency missing. Install with: pip install -e ".[desktop]"') from exc

    class MainWindow(QMainWindow):

        def __init__(self):
            super().__init__()
            self.setWindowTitle("Odoo Addon Migrator — v0.1")
            self.resize(820, 620)

            self.source_box = QComboBox(); self.source_box.addItems([str(v) for v in range(14, 20)])
            self.target_box = QComboBox()
            self.addons_edit = QLineEdit()
            self.output_edit = QLineEdit()
            self.path_label = QLabel()
            self.log = QTextEdit(); self.log.setReadOnly(True)

            self.source_box.currentTextChanged.connect(self.refresh_targets)
            self.target_box.currentTextChanged.connect(self.refresh_plan)

            form = QFormLayout()
            form.addRow("Source Odoo version", self.source_box)
            form.addRow("Target Odoo version", self.target_box)
            form.addRow("Custom addons", self._path_row(self.addons_edit, False))
            form.addRow("Output folder", self._path_row(self.output_edit, True))
            form.addRow("Migration path", self.path_label)

            ensure_btn = QPushButton("Cache Source + Target")
            ensure_btn.clicked.connect(self.ensure_sources)
            migrate_btn = QPushButton("Create Migrated Copy")
            migrate_btn.clicked.connect(self.run_migration)
            buttons = QHBoxLayout(); buttons.addWidget(ensure_btn); buttons.addWidget(migrate_btn)

            layout = QVBoxLayout(); layout.addLayout(form); layout.addLayout(buttons); layout.addWidget(self.log)
            container = QWidget(); container.setLayout(layout); self.setCentralWidget(container)
            self.refresh_targets()

        def _path_row(self, edit: QLineEdit, output: bool):
            wrapper = QWidget(); row = QHBoxLayout(wrapper); row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(edit)
            btn = QPushButton("Browse")

            def choose():
                path = QFileDialog.getExistingDirectory(self, "Select folder")
                if path: edit.setText(path)

            btn.clicked.connect(choose); row.addWidget(btn)
            return wrapper

        def refresh_targets(self):
            src = int(self.source_box.currentText())
            current = self.target_box.currentText()
            self.target_box.blockSignals(True); self.target_box.clear()
            self.target_box.addItems([str(v) for v in range(src + 1, 20)])
            if current and int(current) > src:
                self.target_box.setCurrentText(current)
            self.target_box.blockSignals(False)
            self.refresh_plan()

        def refresh_plan(self):
            if not self.target_box.currentText():
                self.path_label.setText("No higher supported target")
                return
            p = build_plan(int(self.source_box.currentText()), int(self.target_box.currentText()))
            self.path_label.setText(p.path_label)

        def ensure_sources(self):
            if not self.target_box.currentText(): return
            src, dst = int(self.source_box.currentText()), int(self.target_box.currentText())
            manager = SourceManager()
            QApplication.setOverrideCursor(Qt.WaitCursor) if False else None
            try:
                self.log.append(f"Caching official Odoo {src}.0 source...")
                a = manager.ensure(src)
                self.log.append(f"✓ {src}.0 @ {a.commit[:12]}")
                self.log.append(f"Caching official Odoo {dst}.0 source...")
                b = manager.ensure(dst)
                self.log.append(f"✓ {dst}.0 @ {b.commit[:12]}")
            except SourceManagerError as exc:
                QMessageBox.critical(self, "Source error", str(exc))

        def run_migration(self):
            try:
                src = int(self.source_box.currentText()); dst = int(self.target_box.currentText())
                input_root = Path(self.addons_edit.text())
                output_root = Path(self.output_edit.text())
                result = MigrationEngine().migrate(input_root, output_root, src, dst)
                self.log.append(f"✓ Created: {result.output}")
                self.log.append(f"Applied {len(result.changes)} safe change(s).")
            except Exception as exc:
                QMessageBox.critical(self, "Migration error", str(exc))

    app = QApplication(sys.argv)
    window = MainWindow(); window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
