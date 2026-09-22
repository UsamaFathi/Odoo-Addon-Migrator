from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLayout, QListWidget, QPushButton, QProgressBar, QSizePolicy, QSplitter, QVBoxLayout, QWidget

from odoo_migrator.ui.models.application_state import finding_counts
from odoo_migrator.ui.widgets.design_system import MetricCard, SectionHeader, StatusBadge, SurfaceCard
from odoo_migrator.ui.widgets.finding_details import FindingDetails
from odoo_migrator.ui.widgets.findings_table import FindingsTable


class AnalysisPage(QWidget):
    migrateRequested = Signal()
    backRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stage = QLabel("Ready to analyze"); self.stage.setObjectName("muted")
        self.context = QLabel(""); self.context.setObjectName("muted")
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.cards = {name: MetricCard(title) for name, title in (("addons", "Modules"), ("auto_fix", "Auto fixes"), ("resolved", "Auto-resolved"), ("blocker", "Blockers"), ("review_required", "Review required"), ("warning", "Warnings"), ("steps", "Migration steps"))}
        self.findings = FindingsTable(); self.details = FindingDetails(); self.findings.findingSelected.connect(self.details.setFinding)
        self.fixes = QListWidget(); self.fixes.setMinimumHeight(118)
        self.blocker_banner = StatusBadge("", "badgeDanger"); self.blocker_banner.hide()
        self.migrate_button = QPushButton("Start migration  →"); self.migrate_button.clicked.connect(self.migrateRequested); self.migrate_button.setEnabled(False)
        self.back_button = QPushButton("← Back to project"); self.back_button.setObjectName("secondary"); self.back_button.clicked.connect(self.backRequested)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self); layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize); layout.setContentsMargins(28, 24, 28, 28); layout.setSpacing(16)
        layout.addWidget(SectionHeader("Analysis & review", "Source-aware findings, safe fixes, and the evidence behind your migration.")); layout.addWidget(self.context)
        self.progress_card = SurfaceCard(); p = QVBoxLayout(self.progress_card); p.setContentsMargins(16, 12, 16, 12); p.setSpacing(10); p.addWidget(self.stage); p.addWidget(self.progress); layout.addWidget(self.progress_card)
        cards = QGridLayout(); cards.setHorizontalSpacing(10); cards.setVerticalSpacing(10)
        for index, card in enumerate(self.cards.values()):
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            cards.addWidget(card, index // 3, index % 3)
        for column in range(3): cards.setColumnStretch(column, 1)
        layout.addLayout(cards); layout.addWidget(self.blocker_banner)
        fixes_header = QHBoxLayout(); self.fixes_label = QLabel("Automatic fixes"); self.fixes_label.setObjectName("sectionTitle"); fixes_header.addWidget(self.fixes_label); fixes_header.addStretch(); fixes_header.addWidget(QLabel("Only deterministic source-backed changes are applied.")); layout.addLayout(fixes_header); layout.addWidget(self.fixes)
        self.review_splitter = QSplitter(); self.review_splitter.setChildrenCollapsible(False); self.review_splitter.setMinimumHeight(390)
        self.review_splitter.addWidget(self.findings); self.review_splitter.addWidget(self.details); self.review_splitter.setStretchFactor(0, 3); self.review_splitter.setStretchFactor(1, 2); layout.addWidget(self.review_splitter, 1)
        buttons = QHBoxLayout(); buttons.addWidget(self.back_button); buttons.addStretch(); buttons.addWidget(self.migrate_button); layout.addLayout(buttons)

    def set_context(self, source: int, target: int, root) -> None:
        self.context.setText(f"Odoo {source} → Odoo {target}   •   {root}")

    def set_progress(self, stage: str, percent: int) -> None:
        self.stage.setText(stage); self.progress.setValue(percent)

    def set_busy(self, busy: bool) -> None:
        self.back_button.setEnabled(not busy)
        if busy: self.migrate_button.setEnabled(False)

    def set_analysis(self, analysis) -> None:
        counts = finding_counts(analysis)
        self.cards["addons"].set_value(analysis.scan.module_count)
        for key in ("auto_fix", "resolved", "blocker", "review_required", "warning"): self.cards[key].set_value(counts[key])
        self.cards["steps"].set_value(len(analysis.steps)); self.findings.setFindings(analysis.findings); self.fixes.clear()
        for fix in analysis.auto_fix_candidates: self.fixes.addItem(f"✓  {fix.rule_id}  •  {fix.path}  •  {fix.description}")
        if not analysis.auto_fix_candidates: self.fixes.addItem("No automatic changes planned")
        resolved = len(getattr(analysis, "resolved_findings", ()))
        if resolved:
            self.fixes.insertItem(0, f"✓  Autonomous planning resolved {resolved} compatibility finding(s)")
        blocked = bool(analysis.blockers)
        self.migrate_button.setEnabled(not blocked)
        self.migrate_button.setText("Continue autonomous migration  →")
        self.blocker_banner.setVisible(blocked)
        if blocked:
            self.blocker_banner.setText(
                f"Autonomous pass resolved {resolved} finding(s)  •  {len(analysis.blockers)} unresolved blocker(s) remain."
            )
        self.stage.setText("Autonomous resolution incomplete" if blocked else "Ready for autonomous migration")
        self.progress.setValue(100)
