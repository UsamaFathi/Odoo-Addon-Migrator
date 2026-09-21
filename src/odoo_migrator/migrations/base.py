from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Change:
    rule_id: str
    path: Path
    description: str


class Classification(str, Enum):
    SAFE_AUTO_FIX = "safe_auto_fix"
    WARNING = "warning"
    REVIEW_REQUIRED = "review_required"
    BLOCKER = "blocker"


class MigrationRule(ABC):
    rule_id: str
    source: int
    target: int
    category: str
    classification: Classification
    description: str
    evidence: str
    automatic: bool

    def __init__(self, source: int, target: int, rule_id: str, category: str,
                 classification: Classification, description: str, evidence: str,
                 automatic: bool = False):
        self.source = source; self.target = target; self.rule_id = rule_id
        self.category = category; self.classification = classification
        self.description = description; self.evidence = evidence; self.automatic = automatic

    @abstractmethod
    def apply(self, root: Path, dry_run: bool = False) -> list[Change]:
        raise NotImplementedError
