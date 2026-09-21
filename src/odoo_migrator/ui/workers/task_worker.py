from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal


class TaskWorker(QObject):
    """Run one application service operation away from the GUI thread."""

    stage = Signal(str, int)
    succeeded = Signal(object)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, operation: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.operation = operation
        self.args = args
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            result = self.operation(*self.args, progress=self._report)
            self.succeeded.emit(result)
        except Exception as exc:  # noqa: BLE001 - converted to a user-facing structured error
            self.failed.emit(str(exc), repr(exc))
        finally:
            self.finished.emit()

    def _report(self, stage: str, percent: int) -> None:
        self.stage.emit(stage, max(0, min(100, int(percent))))
