from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class FindingsModel(QAbstractTableModel):
    headers = ("Severity", "Migration Step", "Addon", "Category", "File", "Line", "Object", "Rule", "Message")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all = []
        self._rows = []
        self.severity = "All"
        self.step = "All"
        self.addon = "All"
        self.search = ""

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.DisplayRole):  # noqa: N802
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        finding = self._rows[index.row()]
        values = (
            finding.severity.value, finding.migration_step or "", finding.module,
            finding.code, finding.path or "", finding.line or "", finding.object_name or "",
            finding.rule_id or "", finding.message,
        )
        return values[index.column()]

    def finding(self, row: int):
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def setFindings(self, findings) -> None:  # noqa: N802
        self.beginResetModel(); self._all = list(findings); self._apply(); self.endResetModel()

    def setFilter(self, *, severity=None, step=None, addon=None, search=None) -> None:  # noqa: N802
        if severity is not None: self.severity = severity
        if step is not None: self.step = step
        if addon is not None: self.addon = addon
        if search is not None: self.search = search
        self.beginResetModel(); self._apply(); self.endResetModel()

    def _apply(self) -> None:
        query = self.search.casefold()
        self._rows = [finding for finding in self._all if
            (self.severity == "All" or finding.severity.value == self.severity)
            and (self.step == "All" or finding.migration_step == self.step)
            and (self.addon == "All" or finding.module == self.addon)
            and (not query or query in " ".join(str(value or "") for value in (
                finding.message, finding.module, finding.path, finding.rule_id, finding.object_name)).casefold())]
