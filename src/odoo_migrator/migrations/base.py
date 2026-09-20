from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Change:
    rule_id: str
    path: Path
    description: str


class MigrationRule(ABC):
    rule_id: str
    source: int
    target: int

    @abstractmethod
    def apply(self, root: Path, dry_run: bool = False) -> list[Change]:
        raise NotImplementedError
