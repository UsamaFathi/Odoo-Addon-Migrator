from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class AddonsModel(QAbstractTableModel):
    headers = ("Addon", "Version", "Dependencies", "Python", "XML", "JS", "Security", "Status")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, ...]] = []
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
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        value = self._rows[index.row()][index.column()]
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return value
        if role == Qt.TextAlignmentRole and index.column() in (3, 4, 5, 6):
            return Qt.AlignCenter
        if role == Qt.ForegroundRole and index.column() == 7:
            return Qt.darkGreen
        return None

    def set_scan(self, scan) -> None:
        rows = []
        for name, module in sorted(scan.index.modules.items()):
            rows.append((
                name,
                str(module.manifest.get("version", "unknown")),
                ", ".join(module.depends),
                str(module.files.get("python", 0)),
                str(module.files.get("xml", 0)),
                str(module.files.get("javascript", 0)),
                str(module.files.get("csv", 0)),
                "Ready",
            ))
        self.beginResetModel()
        self._rows = rows
        self._sort()
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel(); self._rows = []; self.endResetModel()

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:  # noqa: N802
        self._sort_column, self._sort_order = column, order
        self.layoutAboutToBeChanged.emit()
        self._sort()
        self.layoutChanged.emit()

    def _sort(self) -> None:
        numeric = self._sort_column in (3, 4, 5, 6)
        self._rows.sort(
            key=lambda row: int(row[self._sort_column]) if numeric and row[self._sort_column].isdigit() else row[self._sort_column].casefold(),
            reverse=self._sort_order == Qt.DescendingOrder,
        )
