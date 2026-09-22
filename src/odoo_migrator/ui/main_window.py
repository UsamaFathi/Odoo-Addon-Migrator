from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from odoo_migrator import __version__
from odoo_migrator.application.services import AnalysisService, MigrationService, ProjectScanService
from odoo_migrator.migrations.registry import default_registry
from odoo_migrator.sources.manager import SourceManager, SourceManagerError
from odoo_migrator.sources.manager import SourceManager, SourceManagerError
from odoo_migrator.ui.models.application_state import ApplicationState
from odoo_migrator.ui.pages.analysis import AnalysisPage
from odoo_migrator.ui.pages.migration import MigrationPage
from odoo_migrator.ui.pages.project import ProjectPage
from odoo_migrator.ui.pages.results import ResultsPage
from odoo_migrator.ui.theme import APP_STYLE
from odoo_migrator.ui.widgets.step_indicator import StepIndicator
from odoo_migrator.ui.workers.task_worker import TaskWorker


logger = logging.getLogger("odoo_migrator.ui")


def _display_version(version: str) -> str:
    return version.replace("rc", "-rc.") if "rc" in version else version


def _display_version(version: str) -> str:
    return version.replace("rc", "-rc.") if "rc" in version else version


def configure_logging() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OdooAddonMigrator" / "logs"
    root.mkdir(parents=True, exist_ok=True)
    log_path = root / "application.log"
    if not any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_path for handler in logger.handlers):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return root


class MainWindow(QMainWindow):
    """Thin UI coordinator; all migration work remains in application services."""

    def __init__(self, parent=None, analysis_service=None, migration_service=None, scan_service=None):
        super().__init__(parent)
        self.state = ApplicationState()
        self.registry = default_registry()
        self.analysis_service = analysis_service or AnalysisService(self.registry)
        self.migration_service = migration_service or MigrationService(self.registry)
        self.scan_service = scan_service or ProjectScanService()
        self._thread: QThread | None = None
        self._worker: TaskWorker | None = None
        self._busy = False
        self._log_dir = configure_logging()
        self.settings = QSettings("OdooAddonMigrator", "OdooAddonMigrator")
        self.setWindowTitle("Odoo Addon Migrator")
        self.setMinimumSize(960, 680)
        self.resize(1180, 780)
        self._build()
        self._restore_settings()
        self._log("Application started", version=__version__)

    def _build(self) -> None:
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(28, 22, 28, 12)
        title_row = QHBoxLayout()
        title = QLabel("Odoo Addon Migrator")
        title.setObjectName("appTitle")
        subtitle = QLabel(f"Local  •  Source-Aware  •  Odoo 14–19  •  v{__version__}")
        subtitle.setObjectName("muted")
        title_row.addWidget(title)
        title_row.addWidget(subtitle)
        title_row.addStretch()
        about = QPushButton("About")
        about.setObjectName("secondary")
        about.clicked.connect(self._show_about)
        title_row.addWidget(about)
        header_layout.addLayout(title_row)
        self.steps = StepIndicator()
        header_layout.addWidget(self.steps)

        self.project_page = ProjectPage()
        self.analysis_page = AnalysisPage()
        self.migration_page = MigrationPage()
        self.results_page = ResultsPage()
        self.stack = QStackedWidget()
        for page in (self.project_page, self.analysis_page, self.migration_page, self.results_page):
            self.stack.addWidget(page)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 20)
        layout.addWidget(header)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.setStyleSheet(APP_STYLE)

        versions = sorted(self.registry.versions())
        self.project_page.set_source_versions(versions)
        self.project_page.path_picker.pathChanged.connect(self._path_changed)
        self.project_page.sourceChanged.connect(self._source_changed)
        self.project_page.targetChanged.connect(self._target_changed)
        self.project_page.analyzeRequested.connect(self._analyze)
        self.analysis_page.backRequested.connect(lambda: self._show_page(0, 0))
        self.analysis_page.migrateRequested.connect(self._migrate)
        self.results_page.openOutputRequested.connect(self._open_output)
        self.results_page.openReportRequested.connect(self._open_report)
        self.results_page.openDiffRequested.connect(self._open_diff)
        self.results_page.newProjectRequested.connect(self._new_project)
        self.project_page.outputChanged.connect(self._output_changed)
        self.analysis_page.details.openLocation.connect(self._open_finding_location)
        self._refresh_targets()

    def _restore_settings(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        last_path = self.settings.value("last_path", "")
        if last_path and Path(str(last_path)).is_dir():
            self.project_page.path_picker.setPath(str(last_path))

    def closeEvent(self, event) -> None:
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)
        self.settings.setValue("geometry", self.saveGeometry())
        path = self.project_page.path_picker.path()
        if path:
            self.settings.setValue("last_path", str(path))
        super().closeEvent(event)

    def _log(self, message: str, **fields: object) -> None:
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.info("%s%s", message, f" {suffix}" if suffix else "")

    def _show_page(self, index: int, step: int) -> None:
        self.stack.setCurrentIndex(index)
        self.steps.setCurrent(step)

    def _refresh_targets(self) -> None:
        source = self.project_page.selected_source()
        if source is None:
            return
        current = self.project_page.selected_target()
        targets = self.registry.reachable_targets(source)
        self.project_page.set_targets(targets, current if current in targets else (targets[0] if targets else None))
        if targets:
            selected_target = self.project_page.selected_target() or targets[0]
            self.project_page.suggest_output(selected_target)
            self.project_page.set_source_requirements(source, selected_target)
            self._refresh_source_status(source, selected_target)
            self._output_changed(self.project_page.output.text())
        self.state.set_versions(source, self.project_page.selected_target())

    def _refresh_source_status(self, source: int, target: int) -> None:
        try:
            snapshots = self.analysis_service.source_status(source, target)
        except SourceManagerError:
            snapshots = None
        self.project_page.set_source_requirements(source, target, snapshots)

    def _source_changed(self, source: int) -> None:
        self.state.set_versions(source, None)
        self._refresh_targets()
        self._clear_analysis()

    def _target_changed(self, target: int) -> None:
        source = self.project_page.selected_source()
        if source is not None and target in self.registry.reachable_targets(source):
            self.state.set_versions(source, target)
            self.project_page.suggest_output(target)
            self._clear_analysis()

    def _path_changed(self, value: str) -> None:
        self._clear_analysis()
        root = Path(value).resolve() if value else None
        if not root or not root.is_dir():
            self.project_page.set_error("Select a valid folder containing Odoo addons.") if value else None
            return
        self.state.reset_project(root)
        self._start_task(
            "scan", lambda progress=None: self.scan_service.scan(root), (),
            self._scan_done, self.project_page.set_busy,
        )

    def _scan_done(self, token: int, scan) -> None:
        if token != self.state.operation_token:
            return
        self.state.set_scan(scan)
        self.project_page.set_scan(scan)
        if scan.detected_version is not None and not scan.has_version_conflict:
            self.project_page.set_source_versions(sorted(self.registry.versions()), scan.detected_version)
            self._refresh_targets()
        self._log("Project scanned", root=scan.root, modules=scan.module_count)

    def _analyze(self) -> None:
        root = self.project_page.path_picker.path()
        source, target = self.project_page.selected_source(), self.project_page.selected_target()
        if not root or not self.state.scan:
            self._show_error("Choose a valid addons folder first.")
            return
        if target is None:
            self._show_error("No implemented migration target is available from this source version.")
            return
        self.state.set_versions(source, target)
        try:
            snapshots = self.analysis_service.source_status(source, target)
        except SourceManagerError as exc:
            self._show_error("Unable to inspect the local Odoo source cache.", str(exc))
            return
        missing = [version for version, snapshot in snapshots.items() if snapshot is None]
        if missing and not self._confirm_source_download(missing):
            return
        self._show_page(1, 1)
        self._start_task("analysis", lambda progress=None: self.analysis_service.analyze(root, source, target, progress=progress), (), self._analysis_done, self.analysis_page.set_busy)

    def _analysis_done(self, token: int, result) -> None:
        if token != self.state.operation_token:
            return
        self.state.set_analysis(result)
        self.analysis_page.set_analysis(result)
        snapshots = {step.source: step.source_snapshot for step in result.steps}
        snapshots[result.steps[-1].target] = result.steps[-1].target_snapshot if result.steps else result.target_snapshot
        self.project_page.sources.set_versions(list(range(result.plan.source, result.plan.target + 1)), snapshots)
        self.analysis_page.details.set_project_root(result.scan.root)
        self._log("Analysis completed", source=result.plan.source, target=result.plan.target, findings=len(result.findings))

    def _migrate(self) -> None:
        analysis = self.state.analysis
        output = self.project_page.selected_output()
        if not analysis or analysis.blockers:
            self._show_error("Migration is blocked until blocking findings are resolved.")
            return
        if output.exists():
            self._show_error("The selected output directory already exists. Choose a different destination.")
            return
        self.state.set_output_root(output)
        self._show_page(2, 3)
        self.migration_page.set_destination(output)
        self._start_task("migration", lambda progress=None: self.migration_service.migrate(
            self.state.project_root, output, analysis, progress=progress), (), self._migration_done, self.migration_page.set_busy)

    def _migration_done(self, token: int, result) -> None:
        if token != self.state.operation_token:
            return
        self.state.set_migration(result)
        self.results_page.set_result(result, self.state.analysis)
        self._show_page(3, 4)
        self._log("Migration completed", output=result.output)

    def _clear_analysis(self) -> None:
        self.state.analysis = None
        self.state.migration = None
        self.analysis_page.migrate_button.setEnabled(False)

    def _start_task(self, name: str, operation, args: tuple, success, busy_callback) -> None:
        if self._busy:
            self._show_error("Another operation is still running.")
            return
        self._busy = True
        token = self.state.begin_operation(name)
        busy_callback(True)
        thread = QThread(self)
        worker = TaskWorker(operation, *args)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.stage.connect(lambda stage, percent: self._task_stage(token, stage, percent))
        worker.succeeded.connect(lambda result: success(token, result))
        worker.failed.connect(lambda message, details: self._task_failed(token, message, details))
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._task_finished(token, busy_callback))
        self._thread, self._worker = thread, worker
        thread.start()

    def _task_stage(self, token: int, stage: str, percent: int) -> None:
        if token != self.state.operation_token:
            return
        if self.stack.currentWidget() is self.analysis_page:
            self.analysis_page.set_progress(stage, percent)
        elif self.stack.currentWidget() is self.migration_page:
            self.migration_page.set_progress(stage, percent)

    def _task_failed(self, token: int, message: str, details: str) -> None:
        if token != self.state.operation_token:
            return
        self.state.last_error = message
        logger.error("Task failed: %s\n%s", message, details)
        self._show_error(self._friendly_error(message), details)

    @staticmethod
    def _friendly_error(message: str) -> str:
        lowered = message.lower()
        if "git is required" in lowered or ("git" in lowered and "not found" in lowered):
            return ("Git for Windows was not found.\n\nOdoo Addon Migrator uses Git to download verified official "
                    "Odoo Community source snapshots.\n\nInstall Git for Windows and restart the application, "
                    "or use an existing source cache.")
        return message

    def _confirm_source_download(self, versions: list[int]) -> bool:
        names = "\n".join(f"Odoo {version}" for version in versions)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Odoo source files are required")
        box.setText("Odoo source files are required")
        box.setInformativeText(
            f"The following official Community snapshots are not cached:\n\n{names}\n\n"
            "They will be downloaded from the official Odoo GitHub repository and stored locally.\n\nContinue?"
        )
        download = box.addButton("Download and Analyze", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is download

    def _task_finished(self, token: int, busy_callback) -> None:
        if token == self.state.operation_token:
            self._busy = False
            busy_callback(False)
        self._thread = self._worker = None

    def _show_error(self, message: str, details: str = "") -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("Odoo Addon Migrator")
        box.setText(message)
        if details:
            box.setDetailedText(details)
        box.exec()

    def _open_path(self, path: Path | None) -> None:
        if path and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_finding_location(self, path: Path | None) -> None:
        self._open_path(path)

    def _open_output(self) -> None:
        self._open_path(self.state.migration.output if self.state.migration else None)

    def _open_report(self) -> None:
        self._open_path(self.state.migration.report_path if self.state.migration else None)

    def _open_diff(self) -> None:
        self._open_path(self.state.migration.diff_path if self.state.migration else None)

    def _output_changed(self, value: str) -> None:
        self.state.set_output_root(Path(value).resolve() if value.strip() else None)

    def _new_project(self) -> None:
        self.state.reset_project(None)
        self.project_page.path_picker.setPath("")
        self._show_page(0, 0)

    def _show_about(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("About Odoo Addon Migrator")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"<h2>Odoo Addon Migrator</h2><p>Version {__version__}</p><p>Local source-aware migration assistant for Odoo 14–19.</p><p>Independent migration utility. Not affiliated with Odoo S.A.</p>"))
        layout.itemAt(0).widget().setText(f"<h2>Odoo Addon Migrator</h2><p>Version {_display_version(__version__)}</p><p>Supported versions: Odoo 14–19</p><p>Verified source mode: default</p><p>Independent migration utility. Not affiliated with Odoo S.A.</p>")
        project = QPushButton("Open GitHub Project")
        project.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/UsamaFathi/Odoo-Addon-Migrator")))
        cache = QPushButton("Open Source Cache Folder")
        cache.clicked.connect(lambda: self._open_path(SourceManager().cache_root))
        layout.addWidget(project); layout.addWidget(cache)
        logs = QPushButton("Open Logs Folder")
        logs.clicked.connect(lambda: self._open_path(self._log_dir))
        layout.addWidget(logs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
