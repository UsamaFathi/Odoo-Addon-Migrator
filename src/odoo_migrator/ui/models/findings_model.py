from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor


class FindingsModel(QAbstractTableModel):
    headers = ("Severity", "Migration Step", "Addon", "Category", "File", "Line", "Object", "Rule", "Message")
    severity_labels = {"blocker": "BLOCKER", "review_required": "REVIEW", "warning": "WARNING"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all = []
        self._rows = []
        self.severity = "All"
        self.step = "All"
        self.addon = "All"
        self.category = "All"
        self.search = ""
        self._sort_column = 0
        self._sort_order = Qt.AscendingOrder

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        finding = self._rows[index.row()]
        if role == Qt.BackgroundRole and index.column() == 0:
            return {"blocker": QColor("#FEF3F2"), "review_required": QColor("#FFFAEB"), "warning": QColor("#EFF8FF")}.get(finding.severity.value)
        if role == Qt.ForegroundRole and index.column() == 0:
            return {"blocker": QColor("#B42318"), "review_required": QColor("#B54708"), "warning": QColor("#175CD3")}.get(finding.severity.value)
        if role != Qt.DisplayRole:
            return None
        values = (
            self.severity_labels.get(finding.severity.value, finding.severity.value.upper()), finding.migration_step or "", finding.module,
            finding.concern, finding.path or "", finding.line if finding.line is not None else "", finding.object_name or "",
            finding.rule_id or "", finding.message,
        )
        return values[index.column()]

    def finding(self, row: int):
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def setFindings(self, findings) -> None:  # noqa: N802
        self.beginResetModel(); self._all = list(findings); self._apply(); self.endResetModel()

    def setFilter(self, *, severity=None, step=None, addon=None, category=None, search=None) -> None:  # noqa: N802
        if severity is not None: self.severity = severity
        if step is not None: self.step = step
        if addon is not None: self.addon = addon
        if category is not None: self.category = category
        if search is not None: self.search = search
        self.beginResetModel(); self._apply(); self.endResetModel()

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:  # noqa: N802 - Qt model API
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        self._apply()
        self.layoutChanged.emit()

    def _apply(self) -> None:
        query = self.search.casefold()
        self._rows = [finding for finding in self._all if
            (self.severity == "All" or finding.severity.value == self.severity)
            and (self.step == "All" or finding.migration_step == self.step)
            and (self.addon == "All" or finding.module == self.addon)
            and (self.category == "All" or finding.concern == self.category)
            and (not query or query in " ".join(str(value or "") for value in (
                finding.message, finding.module, finding.path, finding.rule_id, finding.object_name, finding.concern)).casefold())]
        descending = getattr(self._sort_order, "name", "") == "DescendingOrder" or self._sort_order == 1
        self._rows.sort(key=self._sort_key, reverse=descending)

    def _sort_key(self, finding):
        values = (
            self.severity_labels.get(finding.severity.value, finding.severity.value.upper()), finding.migration_step or "", finding.module,
            finding.concern, finding.path or "", finding.line if finding.line is not None else -1,
            finding.object_name or "", finding.rule_id or "", finding.message,
        )
        return values[self._sort_column]
