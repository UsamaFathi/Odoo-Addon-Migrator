from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal


class TaskWorker(QObject):
    """Run one application service operation away from the GUI thread."""

    stage = Signal(int, str, int)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal()

    def __init__(self, token: int, operation: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.token = token
        self.operation = operation
        self.args = args
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            result = self.operation(*self.args, progress=self._report)
            self.succeeded.emit(self.token, result)
        except Exception as exc:  # noqa: BLE001 - converted to a user-facing structured error
            self.failed.emit(self.token, str(exc), repr(exc))
        finally:
            self.finished.emit()

    def _report(self, stage: str, percent: int) -> None:
        self.stage.emit(self.token, stage, max(0, min(100, int(percent))))
