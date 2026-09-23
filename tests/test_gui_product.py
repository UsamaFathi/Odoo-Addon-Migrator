from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, QThread, Qt
from PySide6.QtGui import QPixmap, QWheelEvent
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QScrollArea

from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.analysis.project import scan_custom_addons
from odoo_migrator.ui.main_window import MainWindow
from odoo_migrator.ui.app import capture_ui
import odoo_migrator.ui.settings as settings_module
from odoo_migrator.ui.models.application_state import ApplicationState, WorkflowPhase, suggested_output_path
from odoo_migrator.ui.models.findings_model import FindingsModel
from odoo_migrator.ui.pages.project import ProjectPage
from odoo_migrator.ui.pages.results import ResultsPage
from odoo_migrator.ui.widgets.finding_details import FindingDetails
from odoo_migrator.ui.widgets.source_status import SourceStatus
from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.sources.registry import SourceMode, SourceSelection, SourceSnapshot
from odoo_migrator.sources.enterprise import EnterpriseSourceError
import odoo_migrator.ui.main_window as main_window_module


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture(autouse=True)
def isolated_desktop_settings(monkeypatch, tmp_path: Path):
    settings_path = tmp_path / "gui-test.ini"
    settings = QSettings(str(settings_path), QSettings.IniFormat)
    monkeypatch.setattr(settings_module, "production_settings", lambda: settings)
    yield
    settings.clear(); settings.sync()


def _addon(root: Path, name: str, version: str) -> None:
    module = root / name
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(repr({"name": name, "version": version}), encoding="utf-8")
    (module / "models.py").write_text("from odoo import models\n", encoding="utf-8")


def test_project_scan_exposes_statistics_and_mixed_versions(tmp_path: Path):
    _addon(tmp_path, "sale_one", "16.0.1.0.0")
    _addon(tmp_path, "sale_two", "17.0.1.0.0")
    scan = scan_custom_addons(tmp_path)
    assert scan.module_count == 2
    assert scan.version_counts == {16: 1, 17: 1}
    assert scan.detected_version is None
    assert scan.has_version_conflict
    assert scan.file_statistics["python"] == 4


def test_registry_driven_project_targets_and_source_19_no_target(qapp):
    page = ProjectPage()
    page.set_source_versions([14, 15, 16, 17, 18, 19], 18)
    page.set_targets((19,), 19)
    assert page.selected_target() == 19
    page.set_source_versions([14, 15, 16, 17, 18, 19], 19)
    page.set_targets((), None)
    assert page.selected_target() is None
    page.close()


def test_application_state_output_and_blocker_policy():
    state = ApplicationState(project_root=Path("C:/addons"), target_version=19)
    assert suggested_output_path(Path("C:/addons"), 19) == Path("C:/addons_19")
    state.begin_operation("analysis")
    assert state.phase is WorkflowPhase.ANALYZE
    state.set_output_root(Path("C:/addons_19"))
    finding = Finding(Severity.BLOCKER, "model.removed", "sale", "blocked")
    assert not state.can_migrate
    assert finding.severity is Severity.BLOCKER


def test_findings_filter_by_step_and_search(qapp):
    model = FindingsModel()
    model.setFindings([
        Finding(Severity.WARNING, "xml.one", "sale", "old view", rule_id="one", migration_step="17_to_18"),
        Finding(Severity.REVIEW_REQUIRED, "xml.two", "stock", "review asset", rule_id="two", migration_step="18_to_19"),
    ])
    model.setFilter(step="18_to_19")
    assert model.rowCount() == 1 and model.finding(0).module == "stock"
    model.setFilter(step="All", search="asset")
    assert model.rowCount() == 1


def test_findings_category_filter_and_numeric_sorting(qapp):
    from odoo_migrator.ui.models.findings_model import FindingsModel
    model = FindingsModel()
    model.setFindings([
        Finding(Severity.WARNING, "python.method", "sale", "late", line=20, migration_step="18_to_19"),
        Finding(Severity.BLOCKER, "security.model", "base", "early", line=3, migration_step="17_to_18"),
    ])
    model.setFilter(category="method")
    assert model.rowCount() == 1
    model.setFilter(category="All")
    model.sort(5)
    assert model.finding(0).line == 3
    model.sort(5, 1)
    assert model.finding(0).line == 20


def test_source_status_distinguishes_cached_and_missing(qapp, tmp_path: Path):
    status = SourceStatus()
    cached = SourceSnapshot(18, "18.0", "controlled://odoo", "a" * 40, tmp_path, SourceMode.VERIFIED_SNAPSHOT, "a" * 40)
    status.set_versions([17, 18], {17: None, 18: cached})
    text = status.label.text()
    assert "Odoo 17  •  Source required" in text
    assert "Odoo 18  •  Ready locally" in text
    assert "Verified Snapshot" in text


def test_source_status_supports_local_exact_source_card(qapp, tmp_path: Path):
    status = SourceStatus()
    root = tmp_path / "odoo18"
    local = SourceSnapshot(18, "18.0", "", None, root, SourceMode.LOCAL_EXACT_SOURCE, None, None, False, False)
    status.set_versions([18, 19], {18: local, 19: None}, {18: SourceSelection(18, SourceMode.LOCAL_EXACT_SOURCE, root)})
    assert status.cards[0].status.text() == "Local source"
    assert status.cards[0].mode.text() == "Local Exact Source"
    assert status.cards[1].status.text() == "Source required"
    assert status.cards[1].download.text() == "Use verified snapshot"


def test_source_status_accepts_mixed_local_and_verified_selections(tmp_path: Path):
    class Manager:
        def resolve_selection(self, selection):
            return SourceSnapshot(selection.version, f"{selection.version}.0", "", None, selection.path, SourceMode.LOCAL_EXACT_SOURCE)

        def snapshot(self, version, mode=SourceMode.VERIFIED_SNAPSHOT):
            return None

    root = tmp_path / "odoo18"
    result = AnalysisService(source_manager=Manager()).source_status(18, 19, source_selections={18: SourceSelection(18, SourceMode.LOCAL_EXACT_SOURCE, root), 19: SourceSelection(19, SourceMode.VERIFIED_SNAPSHOT)})
    assert result[18].source_mode is SourceMode.LOCAL_EXACT_SOURCE
    assert result[19] is None


def test_analysis_uses_local_18_and_verified_19_without_local_mutation(tmp_path: Path):
    def source_tree(root: Path, version: int) -> Path:
        (root / "odoo").mkdir(parents=True); (root / "addons" / "base").mkdir(parents=True)
        (root / "odoo" / "release.py").write_text(f"version_info = ({version}, 0, 0, 'final', 0)\n", encoding="utf-8")
        (root / "addons" / "base" / "__manifest__.py").write_text(repr({"name": "Base", "version": f"{version}.0.1.0.0"}), encoding="utf-8")
        return root

    local_root = source_tree(tmp_path / "local18", 18); verified_root = source_tree(tmp_path / "verified19", 19)
    local_before = sorted(path.relative_to(local_root).as_posix() for path in local_root.rglob("*"))
    snapshots = {
        18: SourceSnapshot(18, "18.0", "", None, local_root, SourceMode.LOCAL_EXACT_SOURCE),
        19: SourceSnapshot(19, "19.0", "controlled://odoo", "verified-19", verified_root, SourceMode.VERIFIED_SNAPSHOT, "verified-19"),
    }

    class MixedManager:
        def snapshot(self, version, mode=SourceMode.VERIFIED_SNAPSHOT): return None
        def resolve_selection(self, selection): return snapshots[selection.version]

    custom = tmp_path / "custom" / "demo"; custom.mkdir(parents=True)
    manifest = custom / "__manifest__.py"; manifest.write_text(repr({"name": "Demo", "version": "18.0.1.0.0"}), encoding="utf-8")
    result = AnalysisService(source_manager=MixedManager()).analyze(custom.parent, 18, 19, source_selections={18: SourceSelection(18, SourceMode.LOCAL_EXACT_SOURCE, local_root), 19: SourceSelection(19, SourceMode.VERIFIED_SNAPSHOT)})
    assert result.source_snapshot.source_mode is SourceMode.LOCAL_EXACT_SOURCE
    assert result.target_snapshot.source_mode is SourceMode.VERIFIED_SNAPSHOT
    assert sorted(path.relative_to(local_root).as_posix() for path in local_root.rglob("*")) == local_before


def test_analyze_requires_confirmation_when_sources_are_missing(qapp, tmp_path: Path, monkeypatch):
    class _StatusOnly:
        def source_status(self, source, target):
            return {version: None for version in range(source, target + 1)}

        def analyze(self, *args, **kwargs):
            raise AssertionError("analysis must not start after cancellation")

    root = tmp_path / "custom"; _addon(root, "demo", "18.0.1.0.0")
    window = MainWindow(analysis_service=_StatusOnly(), migration_service=MigrationService())
    window.project_page.path_picker.edit.blockSignals(True); window.project_page.path_picker.setPath(root); window.project_page.path_picker.edit.blockSignals(False)
    window.state.reset_project(root); window.state.set_scan(scan_custom_addons(root))
    window.project_page.set_source_versions([18, 19], 18); window.project_page.set_targets((19,), 19)
    monkeypatch.setattr(window, "_confirm_source_setup", lambda versions: False)
    monkeypatch.setattr(window, "_confirm_source_download", lambda versions: False)
    window._analyze()
    assert window.stack.currentIndex() == 0
    window.close()


def test_pytest_paths_never_enter_production_settings(qapp, tmp_path: Path):
    production = QSettings("OdooAddonMigrator", "OdooAddonMigrator")
    production.remove("last_path")
    root = tmp_path / "custom_addons"; _addon(root, "demo", "18.0.1.0.0")
    window = MainWindow()
    window.project_page.path_picker.edit.blockSignals(True); window.project_page.path_picker.setPath(root); window.project_page.path_picker.edit.blockSignals(False)
    window.state.reset_project(root); window.state.set_scan(scan_custom_addons(root)); window.close()
    assert "pytest-of-" not in str(production.value("last_path", ""))
    assert not production.value("last_path", "")


def test_stale_temp_last_path_is_not_restored(qapp, tmp_path: Path):
    settings = QSettings(str(tmp_path / "stale.ini"), QSettings.IniFormat)
    settings.setValue("last_path", str(tmp_path / "pytest-of-nami" / "custom_addons")); settings.sync()
    window = MainWindow(settings=settings_module.DesktopSettings(settings))
    assert window.project_page.path_picker.edit.text() == ""
    window.close()


def test_local_source_mapping_persists_only_in_isolated_settings(tmp_path: Path):
    settings = settings_module.DesktopSettings(QSettings(str(tmp_path / "sources.ini"), QSettings.IniFormat))
    root = tmp_path / "odoo18"
    selection = SourceSelection(18, SourceMode.LOCAL_EXACT_SOURCE, root)
    settings.save_source_selection(selection, validated=True)
    loaded = settings.load_source_selection(18)
    assert loaded and loaded.mode is SourceMode.LOCAL_EXACT_SOURCE and loaded.path == root
    settings.forget_source_selection(18)
    assert settings.load_source_selection(18) is None


def _enterprise_selection_window(qapp, tmp_path: Path):
    settings = settings_module.DesktopSettings(
        QSettings(str(tmp_path / "enterprise.ini"), QSettings.IniFormat)
    )
    paths = {version: tmp_path / f"enterprise-{version}" for version in (16, 18, 19)}
    for path in paths.values():
        path.mkdir()
    window = MainWindow(settings=settings)
    for version, path in paths.items():
        window.enterprise_sources[version] = path
        settings.save_enterprise_source(version, path)
    return window, settings, paths


def test_enterprise_selection_is_strictly_per_version(qapp, tmp_path: Path, monkeypatch):
    window, settings, paths = _enterprise_selection_window(qapp, tmp_path)
    selected = tmp_path / "enterprise-17"
    selected.mkdir()
    calls = []
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(selected),
    )
    monkeypatch.setattr(
        main_window_module,
        "resolve_enterprise_source",
        lambda root, version: calls.append((Path(root), version)),
    )

    window._choose_enterprise_source(17)

    assert calls == [(selected.resolve(), 17)]
    assert window.enterprise_sources == {
        16: paths[16], 17: selected.resolve(), 18: paths[18], 19: paths[19]
    }
    assert settings.load_enterprise_source(16) == paths[16]
    assert settings.load_enterprise_source(17) == selected.resolve()
    assert settings.load_enterprise_source(18) == paths[18]
    assert settings.load_enterprise_source(19) == paths[19]
    window.close()


def test_enterprise_change_and_forget_only_affect_clicked_version(qapp, tmp_path: Path, monkeypatch):
    window, settings, paths = _enterprise_selection_window(qapp, tmp_path)
    first = tmp_path / "enterprise-17-first"; first.mkdir()
    second = tmp_path / "enterprise-17-second"; second.mkdir()
    selected = iter((first, second))
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(next(selected)),
    )
    monkeypatch.setattr(main_window_module, "resolve_enterprise_source", lambda root, version: None)

    window._choose_enterprise_source(17)
    window._choose_enterprise_source(17)
    assert window.enterprise_sources[17] == second.resolve()
    assert settings.load_enterprise_source(16) == paths[16]
    assert settings.load_enterprise_source(17) == second.resolve()
    assert settings.load_enterprise_source(18) == paths[18]
    assert settings.load_enterprise_source(19) == paths[19]

    window._forget_enterprise_source(17)
    assert 17 not in window.enterprise_sources
    assert settings.load_enterprise_source(17) is None
    assert window.enterprise_sources[16] == paths[16]
    assert window.enterprise_sources[18] == paths[18]
    assert window.enterprise_sources[19] == paths[19]
    assert settings.load_enterprise_source(16) == paths[16]
    assert settings.load_enterprise_source(18) == paths[18]
    assert settings.load_enterprise_source(19) == paths[19]
    window.close()


def test_invalid_enterprise_selection_does_not_mutate_other_versions(qapp, tmp_path: Path, monkeypatch):
    window, settings, paths = _enterprise_selection_window(qapp, tmp_path)
    invalid = tmp_path / "invalid-enterprise"; invalid.mkdir()
    errors = []
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(invalid),
    )
    monkeypatch.setattr(
        main_window_module,
        "resolve_enterprise_source",
        lambda root, version: (_ for _ in ()).throw(EnterpriseSourceError("wrong version")),
    )
    monkeypatch.setattr(window, "_show_error", lambda title, details="": errors.append((title, details)))

    window._choose_enterprise_source(17)

    assert errors == [("Could not resolve Odoo 17 Enterprise source from the selected repository.", "wrong version")]
    assert window.enterprise_sources == paths
    for version, path in paths.items():
        assert settings.load_enterprise_source(version) == path
    window.close()


def test_rc2_shell_is_usable_at_standard_windows_size(qapp):
    window = MainWindow()
    window.resize(1366, 768); window.show(); qapp.processEvents()
    assert window.steps.isVisible()
    assert window.project_page.analyze_button.isVisible()
    assert window.stack.currentIndex() == 0
    assert window.project_page.analyze_button.geometry().bottom() <= window.project_page.height()
    screenshot = window.grab()
    assert screenshot.width() > 900 and screenshot.height() > 500
    window.close()


@pytest.mark.parametrize("size", [(1233, 726), (1366, 768), (1920, 1080)])
def test_project_setup_card_has_no_overlapping_controls(qapp, size):
    window = MainWindow()
    window.resize(*size)
    window.show()
    qapp.processEvents()
    page = window.project_page
    card = page.setup_card

    assert isinstance(card.layout(), QGridLayout)
    assert page.path_picker.isVisible()
    assert page.path_picker.placeholderText() == "Select your custom_addons folder"
    assert page.browse_button.isVisible()
    assert page.source.height() == page.target.height()

    assert page.path_picker.geometry().bottom() < page.source_label.geometry().top()
    assert page.path_picker.geometry().bottom() < page.target_label.geometry().top()
    assert page.source.geometry().bottom() < page.output_label.geometry().top()
    assert page.target.geometry().bottom() < page.output_label.geometry().top()
    assert page.output.geometry().bottom() < card.contentsRect().bottom()
    assert not page.setup_card.geometry().intersects(page.detection.geometry())
    output_bottom = page.output.mapTo(page, QPoint(0, page.output.height() - 1)).y()
    assert output_bottom < page.detection.geometry().top()

    widgets = [page.path_picker, page.browse_button, page.source, page.target, page.output]
    widgets.extend(card.findChildren(QLabel, "fieldLabel"))
    widgets.extend(card.findChildren(QLabel, "eyebrow"))
    rectangles = []
    for widget in widgets:
        top_left = widget.mapTo(card, QPoint(0, 0))
        rectangles.append((widget, QRect(top_left, widget.size())))
        assert card.rect().contains(rectangles[-1][1]), widget.objectName()

    for index, (left_widget, left_rect) in enumerate(rectangles):
        for right_widget, right_rect in rectangles[index + 1:]:
            assert not left_rect.intersects(right_rect), (
                left_widget.objectName(), left_rect.getRect(),
                right_widget.objectName(), right_rect.getRect(),
            )

    window.close()


def test_worker_callbacks_are_delivered_on_gui_thread(qapp):
    window = MainWindow()
    results = []
    callback_threads = []
    window._show_page(1, 1)
    window.analysis_page.set_progress = lambda _stage, _percent: callback_threads.append(("stage", QThread.currentThread()))

    def operation(progress=None):
        progress("Working", 50)
        return "done"

    def success(_token, result):
        callback_threads.append(("success", QThread.currentThread()))
        results.append(result)

    window._start_task("probe", operation, (), success, lambda _busy: None)
    deadline = time.time() + 5
    while window._busy and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert results == ["done"]
    assert {name for name, _thread in callback_threads} == {"stage", "success"}
    assert all(thread is qapp.thread() for _name, thread in callback_threads)
    window.close()


def test_project_page_scrolls_with_mouse_wheel_without_changing_version(qapp):
    window = MainWindow()
    window.resize(1233, 726)
    window.show()
    qapp.processEvents()
    page = window.project_page
    page.set_source_versions([14, 15, 16, 17, 18, 19], 18)
    selected = page.source.currentText()
    scroll = window.project_scroll.verticalScrollBar()

    assert scroll.maximum() > 0
    scroll.setValue(0)
    position = QPointF(20, 20)
    global_position = QPointF(page.source.mapToGlobal(QPoint(20, 20)))
    combo_wheel = QWheelEvent(position, global_position, QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
    qapp.sendEvent(page.source, combo_wheel)
    qapp.processEvents()
    assert page.source.currentText() == selected
    assert scroll.value() > 0

    scroll.setValue(0)
    viewport_position = QPointF(window.project_scroll.viewport().rect().center())
    viewport_global = QPointF(window.project_scroll.viewport().mapToGlobal(window.project_scroll.viewport().rect().center()))
    page_wheel = QWheelEvent(viewport_position, viewport_global, QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
    qapp.sendEvent(window.project_scroll.viewport(), page_wheel)
    qapp.processEvents()
    assert scroll.value() > 0
    window.close()


def test_every_workflow_page_uses_a_natural_height_scroll_container(qapp):
    window = MainWindow()
    window.resize(1366, 768)
    window.show()
    qapp.processEvents()

    assert all(isinstance(page, QScrollArea) for page in window.page_scrolls)
    assert [page.widget() for page in window.page_scrolls] == [
        window.project_page,
        window.analysis_page,
        window.migration_page,
        window.results_page,
    ]
    for index, scroll in enumerate(window.page_scrolls):
        window._show_page(index, min(index, 4))
        qapp.processEvents()
        page = scroll.widget()
        assert page.height() >= scroll.viewport().height()
        assert page.width() >= scroll.viewport().width()
        assert scroll.horizontalScrollBar().maximum() == 0
    assert window.analysis_scroll.verticalScrollBar().maximum() > 0
    window.close()


def test_remaining_workflow_pages_do_not_overlap_when_rendered(qapp):
    window = MainWindow()
    window.resize(1366, 768)
    window.show()

    window._show_page(1, 2)
    qapp.processEvents()
    analysis = window.analysis_page
    assert analysis.progress_card.geometry().bottom() < analysis.cards["addons"].geometry().top()
    assert analysis.cards["warning"].geometry().bottom() < analysis.fixes_label.geometry().top()
    assert analysis.fixes.geometry().bottom() < analysis.review_splitter.geometry().top()

    window._show_page(2, 3)
    qapp.processEvents()
    migration = window.migration_page
    assert migration.safety.geometry().bottom() < migration.progress_card.geometry().top()
    assert migration.stage.geometry().bottom() < migration.destination.geometry().top()
    assert migration.destination.geometry().bottom() < migration.progress.geometry().top()

    window._show_page(3, 4)
    qapp.processEvents()
    results = window.results_page
    assert results.validation.geometry().bottom() < results.summary_card.geometry().top()
    assert results.summary_card.geometry().bottom() < results.metrics["fixes"].geometry().top()
    assert results.metrics["fixes"].geometry().bottom() < results.output_button.geometry().top()
    assert results.output_button.geometry().bottom() < results.new_button.geometry().top()
    window.close()


def test_analysis_page_scrolls_with_mouse_wheel(qapp):
    window = MainWindow()
    window.resize(1366, 768)
    window.show()
    window._show_page(1, 2)
    qapp.processEvents()
    scroll = window.analysis_scroll.verticalScrollBar()
    assert scroll.maximum() > 0
    scroll.setValue(0)
    position = QPointF(window.analysis_scroll.viewport().rect().center())
    global_position = QPointF(window.analysis_scroll.viewport().mapToGlobal(window.analysis_scroll.viewport().rect().center()))
    wheel = QWheelEvent(position, global_position, QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
    qapp.sendEvent(window.analysis_scroll.viewport(), wheel)
    qapp.processEvents()
    assert scroll.value() > 0
    window.close()


def test_native_capture_helper_renders_project_page(qapp, tmp_path: Path):
    output = tmp_path / "project-page.png"
    assert capture_ui(qapp, output)
    image = QPixmap(str(output))
    assert not image.isNull()
    assert image.width() >= 1366
    assert image.height() >= 768


@pytest.mark.parametrize("page_name", ["analysis", "migration", "results"])
def test_native_capture_helper_renders_remaining_pages(qapp, tmp_path: Path, page_name: str):
    output = tmp_path / f"{page_name}-page.png"
    assert capture_ui(qapp, output, page_name)
    image = QPixmap(str(output))
    assert not image.isNull()
    assert image.width() >= 1366
    assert image.height() >= 768


def test_finding_location_is_project_safe(qapp, tmp_path: Path):
    module = tmp_path / "sale"; module.mkdir(); file_path = module / "models.py"; file_path.write_text("# test", encoding="utf-8")
    details = FindingDetails(); details.set_project_root(tmp_path)
    details.setFinding(Finding(Severity.WARNING, "python.method", "sale", "x", path="models.py"))
    assert details._safe_path() == file_path.resolve()
    details.setFinding(Finding(Severity.WARNING, "python.method", "sale", "x", path="../../outside.py"))
    assert details._safe_path() is None


def test_results_use_structured_validation_state(qapp, tmp_path: Path):
    metadata = tmp_path / ".odoo_migrator_run.json"
    metadata.write_text('{"validation": {"state": "passed"}}', encoding="utf-8")
    result = SimpleNamespace(changes=(), output=tmp_path, metadata_path=metadata, validation_state="failed", validation_issues=(object(),))
    analysis = SimpleNamespace(review_required=(), blockers=())
    page = ResultsPage(); page.set_result(result, analysis)
    assert "Static Validation: Failed (1 issue(s))" in page.summary.text()


@dataclass
class _ControlledSources:
    snapshots: dict[int, SourceSnapshot]

    def ensure(self, version: int):
        return self.snapshots[version]


def test_desktop_workflow_uses_real_services_and_preserves_input(qapp, tmp_path: Path):
    custom = tmp_path / "custom_addons" / "demo"
    custom.mkdir(parents=True)
    manifest = custom / "__manifest__.py"
    manifest.write_text("{'name': 'Demo', 'version': '18.0.1.0.0'}", encoding="utf-8")
    before = manifest.read_bytes()
    snapshots = {}
    for version in (18, 19):
        source = tmp_path / f"odoo{version}"
        base = source / "base"
        base.mkdir(parents=True)
        (base / "__manifest__.py").write_text("{'name': 'Base'}", encoding="utf-8")
        snapshots[version] = SourceSnapshot(version, f"{version}.0", "controlled://odoo", f"{version:040d}", source, SourceMode.VERIFIED_SNAPSHOT, f"{version:040d}")
    manager = _ControlledSources(snapshots)
    analysis_service = AnalysisService(source_manager=manager)
    window = MainWindow(analysis_service=analysis_service, migration_service=MigrationService())
    assert window.registry.reachable_targets(14) == (15, 16, 17, 18, 19)
    assert window.registry.reachable_targets(19) == ()
    window.project_page.path_picker.edit.blockSignals(True)
    window.project_page.path_picker.setPath(custom.parent)
    window.project_page.path_picker.edit.blockSignals(False)
    window.state.reset_project(custom.parent)
    scan = scan_custom_addons(custom.parent)
    scan_token = window.state.begin_operation()
    window._scan_done(scan_token, scan)
    window.project_page.set_source_versions([18, 19], 18)
    window._refresh_targets()
    assert window.project_page.selected_target() == 19
    analysis_token = window.state.begin_operation()
    analysis = analysis_service.analyze(custom.parent, 18, 19)
    window._analysis_done(analysis_token, analysis)
    output = tmp_path / "custom_addons_19"
    window.project_page.output.setText(str(output))
    assert window.state.output_root == output.resolve()
    window._migrate()
    deadline = time.time() + 10
    while window.state.migration is None and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert window.state.migration is not None
    assert output.is_dir()
    assert (output / "migration_report.html").exists()
    assert (output / "migration.diff").exists()
    assert "19.0.1.0.0" in (output / "demo" / "__manifest__.py").read_text(encoding="utf-8")
    assert manifest.read_bytes() == before
    window.close()


def test_theme_does_not_paint_every_qwidget_background():
    from odoo_migrator.ui.theme import APP_STYLE
    assert "QMainWindow, QWidget { background" not in APP_STYLE
    assert "QMainWindow { background-color:" in APP_STYLE
    assert "QWidget#appRoot" in APP_STYLE
    assert "QLabel { background-color: transparent; }" in APP_STYLE
    assert "QLineEdit, QComboBox { min-height: 24px; }" in APP_STYLE


def test_git_missing_message_is_cross_platform():
    message = MainWindow._friendly_error("Git is required to download/update Odoo Community source.")
    assert "Git was not found" in message
    assert "Git for Windows" not in message
    assert "Local Exact Source" in message



def test_autonomous_mode_is_enabled_by_default_and_can_be_disabled(qapp):
    page = ProjectPage()
    assert page.autonomous_enabled()
    page.autonomous_mode.setChecked(False)
    assert not page.autonomous_enabled()
    page.close()


def test_clean_analysis_queues_autonomous_migration_only_while_analysis_task_is_active(qapp, monkeypatch):
    window = MainWindow()
    window._busy = True
    window.project_page.autonomous_mode.setChecked(True)
    window.project_page.output.setText("C:/tmp/migrated")
    result = SimpleNamespace(
        blockers=(),
        findings=(),
        auto_fix_candidates=(),
        resolved_findings=(),
        scan=SimpleNamespace(root=Path("C:/tmp/custom"), module_count=0),
        plan=SimpleNamespace(source=18, target=19),
        steps=(),
        review_required=(),
    )
    window.state.operation_token = 1
    window._analysis_done(1, result)
    assert window._auto_migrate_pending
    window._auto_migrate_pending = False
    window._busy = False
    window.close()
