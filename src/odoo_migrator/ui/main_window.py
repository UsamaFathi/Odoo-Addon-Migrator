from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from odoo_migrator import __version__
from odoo_migrator.application.services import AnalysisService, MigrationService, ProjectScanService
from odoo_migrator.migrations.registry import default_registry
from odoo_migrator.sources.manager import SourceManager, SourceManagerError
from odoo_migrator.sources.registry import SourceMode, SourceSelection
from odoo_migrator.ui.icons import app_icon
from odoo_migrator.ui.models.application_state import ApplicationState
from odoo_migrator.ui.pages.analysis import AnalysisPage
from odoo_migrator.ui.pages.migration import MigrationPage
from odoo_migrator.ui.pages.project import ProjectPage
from odoo_migrator.ui.pages.results import ResultsPage
from odoo_migrator.ui.settings import DesktopSettings
from odoo_migrator.ui.theme import APP_STYLE
from odoo_migrator.ui.version import display_version
from odoo_migrator.ui.widgets.step_indicator import StepIndicator
from odoo_migrator.ui.workers.task_worker import TaskWorker


logger = logging.getLogger("odoo_migrator.ui")


class _ProjectScrollArea(QScrollArea):
    """Keep the Project page at its layout minimum and scroll only when needed."""

    def __init__(self, page: ProjectPage, parent=None):
        super().__init__(parent)
        self.setObjectName("projectScroll")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidget(page)
        self.verticalScrollBar().setSingleStep(48)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        page = self.widget()
        if page is None:
            return
        preferred = page.sizeHint().expandedTo(page.minimumSizeHint())
        viewport = self.viewport().size()
        page.resize(max(viewport.width(), preferred.width()), max(viewport.height(), preferred.height()))


def _display_version(version: str) -> str:
    return display_version(version)


def configure_logging() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OdooAddonMigrator" / "logs"; root.mkdir(parents=True, exist_ok=True)
    log_path = root / "application.log"
    if not any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_path for handler in logger.handlers):
        handler = logging.FileHandler(log_path, encoding="utf-8"); handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s")); logger.addHandler(handler); logger.setLevel(logging.INFO)
    return root


class MainWindow(QMainWindow):
    """Desktop shell; application services remain responsible for migration work."""

    def __init__(self, parent=None, analysis_service=None, migration_service=None, scan_service=None, settings=None):
        super().__init__(parent); self.state = ApplicationState(); self.registry = default_registry()
        self.analysis_service = analysis_service or AnalysisService(self.registry); self.migration_service = migration_service or MigrationService(self.registry); self.scan_service = scan_service or ProjectScanService()
        self.source_manager = getattr(self.analysis_service, "source_manager", None) or SourceManager()
        if getattr(self.analysis_service, "source_manager", None) is None: self.analysis_service.source_manager = self.source_manager
        self.source_selections: dict[int, SourceSelection] = {}
        self._thread: QThread | None = None; self._worker: TaskWorker | None = None; self._busy = False; self._task_success_callback = None; self._task_busy_callback = None; self._log_dir = configure_logging()
        if settings is None:
            self.settings = DesktopSettings()
        elif isinstance(settings, QSettings):
            self.settings = DesktopSettings(settings)
        else:
            self.settings = settings
        self.setWindowTitle("Odoo Addon Migrator"); self.setWindowIcon(app_icon()); self.setMinimumSize(1020, 680); self.resize(1240, 800); self._build(); self._restore_settings(); self._log("Application started", version=__version__)

    def _build(self) -> None:
        self.steps = StepIndicator(); self.steps.setFixedWidth(216)
        self.project_page = ProjectPage(); self.project_scroll = _ProjectScrollArea(self.project_page)
        self.analysis_page = AnalysisPage(); self.migration_page = MigrationPage(); self.results_page = ResultsPage(); self.stack = QStackedWidget()
        for page in (self.project_scroll, self.analysis_page, self.migration_page, self.results_page): self.stack.addWidget(page)
        header = QWidget(); header_layout = QHBoxLayout(header); header_layout.setContentsMargins(28, 20, 28, 12)
        identity = QVBoxLayout(); title = QLabel("Odoo Addon Migrator"); title.setObjectName("appTitle"); subtitle = QLabel(f"Local source-aware migration assistant  •  v{_display_version(__version__)}"); subtitle.setObjectName("subtitle"); identity.addWidget(title); identity.addWidget(subtitle); header_layout.addLayout(identity); header_layout.addStretch()
        about = QPushButton("About"); about.setObjectName("secondary"); about.clicked.connect(self._show_about); header_layout.addWidget(about)
        content = QWidget(); content.setObjectName("contentRoot"); content_layout = QVBoxLayout(content); content_layout.setContentsMargins(0, 0, 0, 0); content_layout.addWidget(header); content_layout.addWidget(self.stack, 1)
        root = QWidget(); root.setObjectName("appRoot"); root_layout = QHBoxLayout(root); root_layout.setContentsMargins(0, 0, 0, 0); root_layout.setSpacing(0); root_layout.addWidget(self.steps); root_layout.addWidget(content, 1); self.setCentralWidget(root); self.setStyleSheet(APP_STYLE)
        self.project_page.path_picker.pathChanged.connect(self._path_changed); self.project_page.sourceChanged.connect(self._source_changed); self.project_page.targetChanged.connect(self._target_changed); self.project_page.analyzeRequested.connect(self._analyze); self.project_page.outputChanged.connect(self._output_changed)
        self.analysis_page.backRequested.connect(lambda: self._show_page(0, 0)); self.analysis_page.migrateRequested.connect(self._migrate); self.results_page.openOutputRequested.connect(self._open_output); self.results_page.openReportRequested.connect(self._open_report); self.results_page.openDiffRequested.connect(self._open_diff); self.results_page.newProjectRequested.connect(self._new_project); self.analysis_page.details.openLocation.connect(self._open_finding_location)
        self.project_page.localSourceRequested.connect(self._choose_local_source); self.project_page.downloadSourceRequested.connect(self._choose_verified_source); self.project_page.forgetSourceRequested.connect(self._forget_source)

    def _restore_settings(self) -> None:
        geometry = self.settings.load_geometry()
        if geometry: self.restoreGeometry(geometry)
        last_path = self.settings.load_last_project()
        if last_path: self.project_page.path_picker.setPath(last_path)
        for version in self.registry.versions():
            selection = self.settings.load_source_selection(version)
            if not selection: continue
            if selection.mode is SourceMode.LOCAL_EXACT_SOURCE:
                try: self.source_manager.resolve_selection(selection)
                except SourceManagerError: self.settings.forget_source_selection(version); continue
            self.source_selections[version] = selection

    def closeEvent(self, event) -> None:
        if self._thread and self._thread.isRunning(): self._thread.quit(); self._thread.wait(5000)
        self.settings.save_geometry(self.saveGeometry()); path = self.project_page.path_picker.path(); self.settings.save_last_project(path if self.state.scan else None); super().closeEvent(event)

    def _log(self, message: str, **fields: object) -> None:
        suffix = " ".join(f"{key}={value}" for key, value in fields.items()); logger.info("%s%s", message, f" {suffix}" if suffix else "")

    def _show_page(self, index: int, step: int) -> None:
        self.stack.setCurrentIndex(index); self.steps.setCurrent(step)

    def _refresh_targets(self) -> None:
        source = self.project_page.selected_source()
        if source is None: return
        current = self.project_page.selected_target(); targets = self.registry.reachable_targets(source); self.project_page.set_targets(targets, current if current in targets else (targets[0] if targets else None))
        if targets:
            selected_target = self.project_page.selected_target() or targets[0]; self.project_page.suggest_output(selected_target); self.project_page.set_source_requirements(source, selected_target, selections=self.source_selections); self._refresh_source_status(source, selected_target); self._output_changed(self.project_page.output.text())
        self.state.set_versions(source, self.project_page.selected_target())

    def _refresh_source_status(self, source: int, target: int) -> None:
        try: snapshots = self._source_status(source, target)
        except SourceManagerError: snapshots = None
        self.project_page.set_source_requirements(source, target, snapshots, self.source_selections)

    def _source_status(self, source: int, target: int):
        try:
            return self.analysis_service.source_status(source, target, manager=self.source_manager, source_selections=self.source_selections)
        except TypeError:
            # Preserve compatibility with small test/dry-run service adapters.
            return self.analysis_service.source_status(source, target)

    def _choose_local_source(self, version: int) -> None:
        selected = QFileDialog.getExistingDirectory(self, f"Select Odoo {version} source folder")
        if not selected: return
        selection = SourceSelection(version, SourceMode.LOCAL_EXACT_SOURCE, Path(selected))
        try: snapshot = self.source_manager.resolve_selection(selection)
        except SourceManagerError as exc: self._show_error(str(exc)); return
        self.source_selections[version] = selection; self.settings.save_source_selection(selection, validated=True); self._refresh_source_cards(); self._log("Local Odoo source selected", version=version, path=snapshot.path, commit=snapshot.actual_commit or "unavailable")

    def _choose_verified_source(self, version: int) -> None:
        selection = SourceSelection(version, SourceMode.VERIFIED_SNAPSHOT); self.source_selections[version] = selection; self.settings.save_source_selection(selection); self._refresh_source_cards()

    def _forget_source(self, version: int) -> None:
        self.source_selections.pop(version, None); self.settings.forget_source_selection(version); self._refresh_source_cards()

    def _refresh_source_cards(self) -> None:
        source, target = self.project_page.selected_source(), self.project_page.selected_target()
        if source is not None and target is not None: self._refresh_source_status(source, target)

    def _source_changed(self, source: int) -> None:
        self.state.set_versions(source, None); self._refresh_targets(); self._clear_analysis()

    def _target_changed(self, target: int) -> None:
        source = self.project_page.selected_source()
        if source is not None and target in self.registry.reachable_targets(source):
            self.state.set_versions(source, target); self.project_page.suggest_output(target); self._refresh_source_status(source, target); self._clear_analysis()

    def _path_changed(self, value: str) -> None:
        self._clear_analysis(); root = Path(value).resolve() if value else None
        if not root or not root.is_dir():
            if value: self.project_page.set_error("Select a valid folder containing Odoo addons.")
            return
        self.state.reset_project(root); self._start_task("scan", lambda progress=None: self.scan_service.scan(root), (), self._scan_done, self.project_page.set_busy)

    def _scan_done(self, token: int, scan) -> None:
        if token != self.state.operation_token: return
        self.state.set_scan(scan); self.project_page.set_source_versions(sorted(self.registry.versions()), scan.detected_version if scan.detected_version and not scan.has_version_conflict else None); self.project_page.set_scan(scan)
        if scan.detected_version is not None and not scan.has_version_conflict: self._refresh_targets()
        self._log("Project scanned", root=scan.root, modules=scan.module_count)

    def _analyze(self) -> None:
        root = self.project_page.path_picker.path(); source, target = self.project_page.selected_source(), self.project_page.selected_target()
        if not root or not self.state.scan: self._show_error("Choose a valid addons folder first."); return
        if target is None: self._show_error("No implemented migration target is available from this source version."); return
        self.state.set_versions(source, target)
        try: snapshots = self._source_status(source, target)
        except SourceManagerError as exc: self._show_error("Unable to inspect the local Odoo source cache.", str(exc)); return
        invalid_local = [version for version, snapshot in snapshots.items() if snapshot is None and self.source_selections.get(version, SourceSelection(version)).mode is SourceMode.LOCAL_EXACT_SOURCE]
        if invalid_local:
            self._show_error("One or more selected local Odoo sources are invalid. Choose another folder.", ", ".join(f"Odoo {version}" for version in invalid_local)); return
        missing = [version for version, snapshot in snapshots.items() if snapshot is None]
        unconfigured = [version for version in missing if version not in self.source_selections]
        if unconfigured and not self._confirm_source_setup(unconfigured): return
        if unconfigured:
            try: snapshots = self._source_status(source, target)
            except SourceManagerError as exc: self._show_error("Unable to inspect the selected Odoo sources.", str(exc)); return
            missing = [version for version, snapshot in snapshots.items() if snapshot is None]
        if missing and not self._confirm_source_download(missing): return
        self._show_page(1, 1); self.analysis_page.set_context(source, target, root); self._start_task("analysis", lambda progress=None: self.analysis_service.analyze(root, source, target, progress=progress, source_selections=self.source_selections), (), self._analysis_done, self.analysis_page.set_busy)

    def _analysis_done(self, token: int, result) -> None:
        if token != self.state.operation_token: return
        self.state.set_analysis(result); self.analysis_page.set_analysis(result); self.analysis_page.set_context(result.plan.source, result.plan.target, result.scan.root)
        snapshots = {step.source: step.source_snapshot for step in result.steps}
        if result.steps: snapshots[result.steps[-1].target] = result.steps[-1].target_snapshot
        self.project_page.sources.set_versions(sorted(snapshots), snapshots, self.source_selections); self.analysis_page.details.set_project_root(result.scan.root); self._show_page(1, 2); self._log("Analysis completed", source=result.plan.source, target=result.plan.target, findings=len(result.findings))

    def _migrate(self) -> None:
        analysis = self.state.analysis; output = self.project_page.selected_output()
        if not analysis or analysis.blockers: self._show_error("Migration is blocked until blocking findings are resolved."); return
        if output.exists(): self._show_error("The selected output directory already exists. Choose a different destination."); return
        self.state.set_output_root(output); self._show_page(2, 3); self.migration_page.set_destination(output); self._start_task("migration", lambda progress=None: self.migration_service.migrate(self.state.project_root, output, analysis, progress=progress), (), self._migration_done, self.migration_page.set_busy)

    def _migration_done(self, token: int, result) -> None:
        if token != self.state.operation_token: return
        self.state.set_migration(result); self.results_page.set_result(result, self.state.analysis); self._show_page(3, 4); self._log("Migration completed", output=result.output)

    def _clear_analysis(self) -> None:
        self.state.analysis = None; self.state.migration = None; self.analysis_page.migrate_button.setEnabled(False)

    def _start_task(self, name: str, operation, args: tuple, success, busy_callback) -> None:
        if self._busy: self._show_error("Another operation is still running."); return
        self._busy = True; token = self.state.begin_operation(name); self._task_success_callback = success; self._task_busy_callback = busy_callback; busy_callback(True)
        thread = QThread(self); worker = TaskWorker(token, operation, *args); worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.stage.connect(self._task_stage, Qt.ConnectionType.QueuedConnection)
        worker.succeeded.connect(self._task_succeeded, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._task_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._task_thread_finished, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(thread.deleteLater)
        self._thread, self._worker = thread, worker; thread.start()

    @Slot(int, str, int)
    def _task_stage(self, token: int, stage: str, percent: int) -> None:
        if token != self.state.operation_token: return
        if self.stack.currentWidget() is self.analysis_page: self.analysis_page.set_progress(stage, percent)
        elif self.stack.currentWidget() is self.migration_page: self.migration_page.set_progress(stage, percent)

    @Slot(int, object)
    def _task_succeeded(self, token: int, result) -> None:
        if token != self.state.operation_token or self._task_success_callback is None: return
        self._task_success_callback(token, result)

    @Slot(int, str, str)
    def _task_failed(self, token: int, message: str, details: str) -> None:
        if token != self.state.operation_token: return
        self.state.last_error = message; logger.error("Task failed: %s\n%s", message, details); self._show_error(self._friendly_error(message), details)

    @staticmethod
    def _friendly_error(message: str) -> str:
        lowered = message.lower()
        if "git is required" in lowered or ("git" in lowered and "not found" in lowered): return "Git was not found.\n\nOdoo Addon Migrator uses Git only when it needs to download verified official Odoo Community source snapshots.\n\nInstall Git and restart the application, or select Local Exact Source folders instead."
        return message

    def _confirm_source_download(self, versions: list[int]) -> bool:
        names = "\n".join(f"Odoo {version}" for version in versions); box = QMessageBox(self); box.setIcon(QMessageBox.Information); box.setWindowTitle("Odoo source files are required"); box.setText("Odoo source files are required"); box.setInformativeText(f"The following official Community snapshots are not cached:\n\n{names}\n\nThey will be downloaded from the official Odoo GitHub repository and stored locally.\n\nContinue?"); download = box.addButton("Download and Analyze", QMessageBox.AcceptRole); box.addButton("Cancel", QMessageBox.RejectRole); box.exec(); return box.clickedButton() is download

    def _confirm_source_setup(self, versions: list[int]) -> bool:
        dialog = QDialog(self); dialog.setWindowTitle("Configure Odoo sources"); layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Odoo source required\nChoose a local source or use the verified snapshot for each version. If it is not cached, it will be downloaded when analysis starts."))
        rows: dict[int, QLabel] = {}
        for version in versions:
            row = QHBoxLayout(); title = QLabel(f"Odoo {version}"); state = QLabel("Not configured"); rows[version] = state; local = QPushButton("Select local source"); download = QPushButton("Use verified snapshot"); download.setObjectName("secondary")
            local.clicked.connect(lambda _checked=False, value=version: (self._setup_local_source(dialog, value, rows[value]), refresh()))
            download.clicked.connect(lambda _checked=False, value=version: (self._setup_verified_source(value, rows[value]), refresh()))
            row.addWidget(title); row.addWidget(state, 1); row.addWidget(local); row.addWidget(download); layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel); continue_button = buttons.addButton("Continue when ready", QDialogButtonBox.AcceptRole); continue_button.setEnabled(False); buttons.rejected.connect(dialog.reject); buttons.accepted.connect(dialog.accept); layout.addWidget(buttons)
        def refresh() -> None:
            continue_button.setEnabled(all(version in self.source_selections for version in versions))
        refresh(); return dialog.exec() == QDialog.Accepted

    def _setup_local_source(self, parent: QDialog, version: int, label: QLabel) -> None:
        selected = QFileDialog.getExistingDirectory(parent, f"Select Odoo {version} source folder")
        if not selected: return
        selection = SourceSelection(version, SourceMode.LOCAL_EXACT_SOURCE, Path(selected))
        try: self.source_manager.resolve_selection(selection)
        except SourceManagerError as exc: QMessageBox.warning(parent, "Wrong Odoo source version", str(exc)); return
        self.source_selections[version] = selection; self.settings.save_source_selection(selection, validated=True); label.setText("Local source selected")

    def _setup_verified_source(self, version: int, label: QLabel) -> None:
        selection = SourceSelection(version, SourceMode.VERIFIED_SNAPSHOT); self.source_selections[version] = selection; self.settings.save_source_selection(selection); label.setText("Verified snapshot selected")

    @Slot()
    def _task_thread_finished(self) -> None:
        callback = self._task_busy_callback
        self._busy = False
        if callback: callback(False)
        self._thread = self._worker = None
        self._task_success_callback = self._task_busy_callback = None

    def _show_error(self, message: str, details: str = "") -> None:
        box = QMessageBox(self); box.setIcon(QMessageBox.Critical); box.setWindowTitle("Odoo Addon Migrator"); box.setText(message)
        if details: box.setDetailedText(details)
        box.exec()

    def _open_path(self, path: Path | None) -> None:
        if path and path.exists(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_finding_location(self, path: Path | None) -> None: self._open_path(path)
    def _open_output(self) -> None: self._open_path(self.state.migration.output if self.state.migration else None)
    def _open_report(self) -> None: self._open_path(self.state.migration.report_path if self.state.migration else None)
    def _open_diff(self) -> None: self._open_path(self.state.migration.diff_path if self.state.migration else None)
    def _output_changed(self, value: str) -> None: self.state.set_output_root(Path(value).resolve() if value.strip() else None)

    def _new_project(self) -> None:
        self.state.reset_project(None); self.project_page.clear_project(); self._show_page(0, 0)

    def _show_about(self) -> None:
        dialog = QDialog(self); dialog.setWindowTitle("About Odoo Addon Migrator"); dialog.setWindowIcon(app_icon()); layout = QVBoxLayout(dialog); icon = QLabel(); icon.setPixmap(app_icon().pixmap(64, 64)); layout.addWidget(icon); title = QLabel(f"<h2>Odoo Addon Migrator</h2><p>v{_display_version(__version__)}</p><p>Source-aware migration assistant<br>Odoo 14 → 19</p><p>Independent migration utility.<br>Not affiliated with Odoo S.A.</p>"); layout.addWidget(title)
        project = QPushButton("Open GitHub Project"); project.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/UsamaFathi/Odoo-Addon-Migrator"))); layout.addWidget(project)
        cache = QPushButton("Open Source Cache Folder"); cache.clicked.connect(lambda: self._open_path(SourceManager().cache_root)); layout.addWidget(cache)
        logs = QPushButton("Open Logs Folder"); logs.clicked.connect(lambda: self._open_path(self._log_dir)); layout.addWidget(logs); buttons = QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons); dialog.exec()
