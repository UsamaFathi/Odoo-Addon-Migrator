from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from odoo_migrator.ui.widgets.design_system import MetricCard, SectionHeader, StatusBadge, SurfaceCard


class ResultsPage(QWidget):
    openOutput = Signal(); openReport = Signal(); openDiff = Signal(); newProject = Signal()
    openOutputRequested = openOutput; openReportRequested = openReport; openDiffRequested = openDiff; newProjectRequested = newProject

    def __init__(self, parent=None):
        super().__init__(parent)
        self.summary = QLabel(); self.summary.setWordWrap(True); self.output = QLabel(); self.output.setWordWrap(True); self.output.setObjectName("muted")
        self.validation = StatusBadge("Static validation pending", "badgeInfo")
        self.metrics = {key: MetricCard(label) for key, label in (("fixes", "Automatic fixes"), ("resolved", "Auto-resolved"), ("review", "Review notes"), ("blockers", "Blockers"))}
        self.report = QPushButton("Open migration report"); self.report.clicked.connect(self.openReport); self.diff = QPushButton("Review changes / diff"); self.diff.clicked.connect(self.openDiff)
        self.output_button = QPushButton("Open output folder"); self.output_button.clicked.connect(self.openOutput)
        self.new_button = QPushButton("Start another project"); self.new_button.setObjectName("secondary"); self.new_button.clicked.connect(self.newProject)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self); layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize); layout.setContentsMargins(28, 24, 28, 28); layout.setSpacing(16)
        layout.addWidget(SectionHeader("Migration complete", "Review the output and validate it on the target Odoo installation before production use.")); layout.addWidget(self.validation)
        self.summary_card = SurfaceCard(); self.summary_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        inner = QVBoxLayout(self.summary_card); inner.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize); inner.setContentsMargins(20, 18, 20, 18); inner.setSpacing(10); inner.addWidget(self.summary); inner.addWidget(self.output); layout.addWidget(self.summary_card)
        cards = QGridLayout(); cards.setHorizontalSpacing(10); cards.setVerticalSpacing(10)
        for column, metric in enumerate(self.metrics.values()):
            metric.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            cards.addWidget(metric, 0, column); cards.setColumnStretch(column, 1)
        layout.addLayout(cards)
        buttons = QGridLayout(); buttons.setHorizontalSpacing(10); buttons.setVerticalSpacing(10)
        buttons.addWidget(self.output_button, 0, 0); buttons.addWidget(self.report, 0, 1); buttons.addWidget(self.diff, 0, 2)
        buttons.addWidget(self.new_button, 1, 2); buttons.setColumnStretch(0, 1); buttons.setColumnStretch(1, 1); buttons.setColumnStretch(2, 1)
        layout.addLayout(buttons); layout.addStretch()

    def set_result(self, result, analysis=None) -> None:
        state = getattr(result, "validation_state", None); issues = getattr(result, "validation_issues", ())
        metadata = {}
        if result.metadata_path and result.metadata_path.exists():
            try:
                metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                metadata = {}
        if state in (None, "not_run"):
            validation = metadata.get("validation", {})
            state, issues = validation.get("state", "failed"), validation.get("issues", ())

        state = state or "failed"; passed = state == "passed"; issue_count = len(issues)
        self.validation.setText("Static validation passed" if passed else f"Static validation failed  •  {issue_count} issue(s)")
        self.validation.set_role("badgeSuccess" if passed else "badgeDanger")

        plan = getattr(analysis, "plan", None)
        if plan:
            source_version, target_version = plan.source, plan.target
        else:
            source_version = metadata.get("source_version")
            target_version = metadata.get("target_version")
        path_text = (
            f"Odoo {source_version} → Odoo {target_version}\n\n"
            if source_version is not None and target_version is not None else ""
        )
        resolved = len(getattr(analysis, "resolved_findings", ())) if analysis is not None else 0
        review_required = len(getattr(analysis, "review_required", ())) if analysis is not None else 0
        blockers = len(getattr(analysis, "blockers", ())) if analysis is not None else 0
        engine = metadata.get("engine")
        engine_text = "Migration Brain" if engine == "migration_brain" else "Source-aware engine"
        issue_text = f" ({issue_count} issue(s))" if issue_count else ""
        self.summary.setText(
            f"{path_text}{engine_text}\n"
            f"Automatic fixes applied: {len(result.changes)}\n"
            f"Auto-resolved findings: {resolved}\n"
            f"Review notes remaining: {review_required}\n"
            f"Blockers: {blockers}\n"
            f"Static Validation: {'Passed' if passed else 'Failed'}{issue_text}\n\n"
            f"Static validation {'passed' if passed else 'failed'}. "
            "Install and test the migrated addons on the target Odoo version before production use."
        )
        self.output.setText(f"Output folder\n{result.output}")
        self.metrics["fixes"].set_value(len(result.changes))
        self.metrics["resolved"].set_value(resolved)
        self.metrics["review"].set_value(review_required)
        self.metrics["blockers"].set_value(blockers)

        report_path = getattr(result, "report_path", None)
        diff_path = getattr(result, "diff_path", None)
        self.report.setEnabled(bool(report_path and report_path.exists()))
        self.diff.setEnabled(bool(diff_path and diff_path.exists()))
