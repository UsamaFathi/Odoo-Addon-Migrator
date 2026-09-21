from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QProgressBar, QSplitter, QVBoxLayout, QWidget

from odoo_migrator.ui.widgets.finding_details import FindingDetails
from odoo_migrator.ui.widgets.findings_table import FindingsTable
from odoo_migrator.ui.widgets.status_card import StatusCard
from odoo_migrator.ui.models.application_state import finding_counts


class AnalysisPage(QWidget):
    migrateRequested = Signal()
    backRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stage = QLabel("Ready to analyze"); self.stage.setObjectName("muted")
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.cards = {name: StatusCard(title) for name, title in (("addons", "Addons"), ("auto_fix", "Auto Fixes"), ("blocker", "Blockers"), ("review_required", "Review Required"), ("warning", "Warnings"), ("steps", "Migration Steps"))}
        cards = QHBoxLayout()
        for card in self.cards.values(): cards.addWidget(card)
        self.findings = FindingsTable(); self.details = FindingDetails(); self.findings.findingSelected.connect(self.details.setFinding)
        self.fixes = QListWidget(); self.fixes.setMaximumHeight(115)
        self.migrate_button = QPushButton("Start Migration"); self.migrate_button.clicked.connect(self.migrateRequested); self.migrate_button.setEnabled(False)
        self.back_button = QPushButton("Back to Project"); self.back_button.setObjectName("secondary"); self.back_button.clicked.connect(self.backRequested)
        splitter = QSplitter(); splitter.addWidget(self.findings); splitter.addWidget(self.details); splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 2)
        layout = QVBoxLayout(self); layout.addWidget(QLabel("Analysis and review", objectName="sectionTitle")); layout.addWidget(self.stage); layout.addWidget(self.progress); layout.addLayout(cards); layout.addWidget(QLabel("Automatic fixes planned", objectName="sectionTitle")); layout.addWidget(self.fixes); layout.addWidget(splitter, 1)
        buttons = QHBoxLayout(); buttons.addWidget(self.back_button); buttons.addStretch(); buttons.addWidget(self.migrate_button); layout.addLayout(buttons)

    def set_progress(self, stage: str, percent: int) -> None:
        self.stage.setText(stage); self.progress.setValue(percent)

    def set_busy(self, busy: bool) -> None:
        self.back_button.setEnabled(not busy)
        if busy:
            self.migrate_button.setEnabled(False)

    def set_analysis(self, analysis) -> None:
        counts = finding_counts(analysis)
        self.cards["addons"].setValue(analysis.scan.module_count); self.cards["auto_fix"].setValue(counts["auto_fix"]); self.cards["blocker"].setValue(counts["blocker"]); self.cards["review_required"].setValue(counts["review_required"]); self.cards["warning"].setValue(counts["warning"]); self.cards["steps"].setValue(len(analysis.steps))
        self.findings.setFindings(analysis.findings); self.fixes.clear()
        for fix in analysis.auto_fix_candidates: self.fixes.addItem(f"{fix.rule_id}  •  {fix.path}  •  {fix.description}")
        self.migrate_button.setEnabled(not analysis.blockers)
        self.stage.setText("Migration blocked" if analysis.blockers else "Analysis complete")
        self.progress.setValue(100)
