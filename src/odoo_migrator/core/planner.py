from __future__ import annotations

from dataclasses import dataclass
from .versions import normalize_version


@dataclass(frozen=True, slots=True)
class MigrationStep:
    source: int
    target: int

    @property
    def key(self) -> str:
        return f"{self.source}_to_{self.target}"


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    source: int
    target: int
    steps: tuple[MigrationStep, ...]

    @property
    def path_label(self) -> str:
        return " → ".join(map(str, range(self.source, self.target + 1)))


def build_plan(source: int | str, target: int | str) -> MigrationPlan:
    src = normalize_version(source)
    dst = normalize_version(target)
    if dst <= src:
        raise ValueError("Target version must be higher than source version.")
    steps = tuple(MigrationStep(v, v + 1) for v in range(src, dst))
    return MigrationPlan(src, dst, steps)
