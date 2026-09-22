from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QProgressBar, QSplitter, QVBoxLayout, QWidget

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
        self.cards = {name: MetricCard(title) for name, title in (("addons", "Modules"), ("auto_fix", "Auto fixes"), ("blocker", "Blockers"), ("review_required", "Review required"), ("warning", "Warnings"), ("steps", "Migration steps"))}
        self.findings = FindingsTable(); self.details = FindingDetails(); self.findings.findingSelected.connect(self.details.setFinding)
        self.fixes = QListWidget(); self.fixes.setMaximumHeight(112)
        self.blocker_banner = StatusBadge("", "badgeDanger"); self.blocker_banner.hide()
        self.migrate_button = QPushButton("Start migration  →"); self.migrate_button.clicked.connect(self.migrateRequested); self.migrate_button.setEnabled(False)
        self.back_button = QPushButton("← Back to project"); self.back_button.setObjectName("secondary"); self.back_button.clicked.connect(self.backRequested)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 20); layout.setSpacing(12)
        layout.addWidget(SectionHeader("Analysis & review", "Source-aware findings, safe fixes, and the evidence behind your migration.")); layout.addWidget(self.context)
        progress_card = SurfaceCard(); p = QVBoxLayout(progress_card); p.setContentsMargins(16, 12, 16, 12); p.addWidget(self.stage); p.addWidget(self.progress); layout.addWidget(progress_card)
        cards = QHBoxLayout(); cards.setSpacing(8)
        for card in self.cards.values(): cards.addWidget(card)
        layout.addLayout(cards); layout.addWidget(self.blocker_banner)
        fixes_header = QHBoxLayout(); label = QLabel("Automatic fixes"); label.setObjectName("sectionTitle"); fixes_header.addWidget(label); fixes_header.addStretch(); fixes_header.addWidget(QLabel("Only deterministic source-backed changes are applied.")); layout.addLayout(fixes_header); layout.addWidget(self.fixes)
        splitter = QSplitter(); splitter.addWidget(self.findings); splitter.addWidget(self.details); splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 2); layout.addWidget(splitter, 1)
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
        for key in ("auto_fix", "blocker", "review_required", "warning"): self.cards[key].set_value(counts[key])
        self.cards["steps"].set_value(len(analysis.steps)); self.findings.setFindings(analysis.findings); self.fixes.clear()
        for fix in analysis.auto_fix_candidates: self.fixes.addItem(f"✓  {fix.rule_id}  •  {fix.path}  •  {fix.description}")
        if not analysis.auto_fix_candidates: self.fixes.addItem("No automatic changes planned")
        blocked = bool(analysis.blockers); self.migrate_button.setEnabled(not blocked); self.blocker_banner.setVisible(blocked)
        if blocked: self.blocker_banner.setText(f"Migration blocked  •  Resolve {len(analysis.blockers)} blocking finding(s) before continuing.")
        self.stage.setText("Migration blocked" if blocked else "Analysis complete"); self.progress.setValue(100)
