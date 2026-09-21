from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class ResultsPage(QWidget):
    openOutput = Signal(); openReport = Signal(); openDiff = Signal(); newProject = Signal()
    openOutputRequested = openOutput
    openReportRequested = openReport
    openDiffRequested = openDiff
    newProjectRequested = newProject

    def __init__(self, parent=None):
        super().__init__(parent)
        self.summary = QLabel(); self.summary.setWordWrap(True)
        self.output = QLabel(); self.output.setWordWrap(True)
        self.report = QPushButton("Open Migration Report"); self.report.clicked.connect(self.openReport)
        self.diff = QPushButton("Review Changes / Diff"); self.diff.clicked.connect(self.openDiff)
        output = QPushButton("Open Output Folder"); output.clicked.connect(self.openOutput)
        new = QPushButton("Start Another Project"); new.setObjectName("secondary"); new.clicked.connect(self.newProject)
        layout = QVBoxLayout(self); layout.addWidget(QLabel("Migration completed", objectName="sectionTitle")); layout.addWidget(self.summary); layout.addWidget(self.output); layout.addWidget(output); layout.addWidget(self.report); layout.addWidget(self.diff); layout.addWidget(new); layout.addStretch()

    def set_result(self, result, analysis) -> None:
        validation = "Passed" if result.metadata_path and "\"state\": \"passed\"" in result.metadata_path.read_text(encoding="utf-8") else "See report"
        self.summary.setText(f"Automatic fixes applied: {len(result.changes)}\nManual review items remaining: {len(analysis.review_required)}\nBlockers: {len(analysis.blockers)}\nStatic Validation: {validation}")
        self.output.setText(f"Output:\n{result.output}")
