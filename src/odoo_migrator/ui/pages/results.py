from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from odoo_migrator.ui.widgets.design_system import MetricCard, SectionHeader, StatusBadge, SurfaceCard


class ResultsPage(QWidget):
    openOutput = Signal(); openReport = Signal(); openDiff = Signal(); newProject = Signal()
    openOutputRequested = openOutput; openReportRequested = openReport; openDiffRequested = openDiff; newProjectRequested = newProject

    def __init__(self, parent=None):
        super().__init__(parent)
        self.summary = QLabel(); self.summary.setWordWrap(True); self.output = QLabel(); self.output.setWordWrap(True); self.output.setObjectName("muted")
        self.validation = StatusBadge("Static validation pending", "badgeInfo")
        self.metrics = {key: MetricCard(label) for key, label in (("fixes", "Automatic fixes"), ("review", "Manual review"), ("blockers", "Blockers"))}
        self.report = QPushButton("Open migration report"); self.report.clicked.connect(self.openReport); self.diff = QPushButton("Review changes / diff"); self.diff.clicked.connect(self.openDiff)
        output = QPushButton("Open output folder"); output.clicked.connect(self.openOutput); new = QPushButton("Start another project"); new.setObjectName("secondary"); new.clicked.connect(self.newProject)
        self._build(output, new)

    def _build(self, output, new) -> None:
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 20); layout.setSpacing(14)
        layout.addWidget(SectionHeader("Migration complete", "Review the output and validate it on the target Odoo installation before production use.")); layout.addWidget(self.validation)
        card = SurfaceCard(); inner = QVBoxLayout(card); inner.setContentsMargins(18, 16, 18, 16); inner.addWidget(self.summary); inner.addWidget(self.output); layout.addWidget(card)
        cards = QHBoxLayout(); [cards.addWidget(card) for card in self.metrics.values()]; layout.addLayout(cards)
        buttons = QHBoxLayout(); buttons.addWidget(output); buttons.addWidget(self.report); buttons.addWidget(self.diff); buttons.addStretch(); buttons.addWidget(new); layout.addLayout(buttons); layout.addStretch()

    def set_result(self, result, analysis) -> None:
        state = getattr(result, "validation_state", None); issues = getattr(result, "validation_issues", ())
        if state in (None, "not_run") and result.metadata_path and result.metadata_path.exists():
            try:
                metadata = json.loads(result.metadata_path.read_text(encoding="utf-8")); validation = metadata.get("validation", {})
                state, issues = validation.get("state", "failed"), validation.get("issues", ())
            except (OSError, ValueError, TypeError): state, issues = "failed", ()
        state = state or "failed"; passed = state == "passed"; issue_count = len(issues)
        self.validation.setText("Static validation passed" if passed else f"Static validation failed  •  {issue_count} issue(s)")
        self.validation.set_role("badgeSuccess" if passed else "badgeDanger")
        plan = getattr(analysis, "plan", None)
        path_text = f"Odoo {plan.source} → Odoo {plan.target}\n\n" if plan else ""
        issue_text = f" ({issue_count} issue(s))" if issue_count else ""
        self.summary.setText(f"{path_text}Automatic fixes applied: {len(result.changes)}\nManual review items remaining: {len(analysis.review_required)}\nBlockers: {len(analysis.blockers)}\nStatic Validation: {'Passed' if passed else 'Failed'}{issue_text}\n\nStatic validation {'passed' if passed else 'failed'}. Install and test the migrated addons on the target Odoo version before production use.")
        self.output.setText(f"Output folder\n{result.output}")
        self.metrics["fixes"].set_value(len(result.changes)); self.metrics["review"].set_value(len(analysis.review_required)); self.metrics["blockers"].set_value(len(analysis.blockers))
