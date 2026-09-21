from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from odoo_migrator.analysis.compat import Finding
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.base import MigrationRule
from odoo_migrator.migrations.v14_to_v15.manifest import Manifest14To15Rule
from odoo_migrator.migrations.v14_to_v15 import frontend, python, reports, security, xml
from odoo_migrator.migrations.v15_to_v16.manifest import Manifest15To16Rule
from odoo_migrator.migrations.v15_to_v16 import frontend as frontend16, python as python16, reports as reports16, security as security16, xml as xml16
from odoo_migrator.migrations.v16_to_v17.manifest import Manifest16To17Rule
from odoo_migrator.migrations.v16_to_v17 import dependencies as dependencies17, frontend as frontend17, python as python17, reports as reports17, security as security17, xml as xml17
from odoo_migrator.migrations.v17_to_v18.manifest import Manifest17To18Rule
from odoo_migrator.migrations.v17_to_v18 import dependencies as dependencies18, frontend as frontend18, python as python18, reports as reports18, security as security18, xml as xml18
from odoo_migrator.migrations.v18_to_v19.manifest import Manifest18To19Rule
from odoo_migrator.migrations.v18_to_v19 import dependencies as dependencies19, frontend as frontend19, python as python19, reports as reports19, security as security19, xml as xml19

Analyzer = Callable[[OdooIndex, OdooIndex, OdooIndex, SourceDiff], list[Finding]]


@dataclass(frozen=True, slots=True)
class MigrationPack:
    source: int
    target: int
    analyzers: tuple[Analyzer, ...] = ()
    rule_factory: Callable[[], list[MigrationRule]] = lambda: []


@dataclass(frozen=True, slots=True)
class UnsupportedMigrationStep:
    source: int
    target: int

    @property
    def label(self) -> str:
        return f"{self.source} -> {self.target}"


class UnsupportedMigrationPathError(ValueError):

    def __init__(self, steps: tuple[UnsupportedMigrationStep, ...]):
        self.steps = steps
        labels = ", ".join(step.label for step in steps)
        super().__init__(f"Migration path is not fully supported. Missing packs: {labels}")


class MigrationPackRegistry:

    def __init__(self):
        self._packs: dict[tuple[int, int], MigrationPack] = {}

    def register(self, pack: MigrationPack) -> None:
        if pack.target != pack.source + 1:
            raise ValueError("Migration packs must target the next adjacent Odoo version.")
        key = (pack.source, pack.target)
        if key in self._packs:
            raise ValueError(f"Migration pack already registered: {pack.source} -> {pack.target}")
        if any(not callable(analyzer) for analyzer in pack.analyzers):
            raise TypeError("Every migration-pack analyzer must be callable.")
        rules = pack.rule_factory()
        for rule in rules:
            if (rule.source, rule.target) != key:
                raise ValueError(f"Rule {rule.rule_id} does not match its migration pack.")
            for attribute in ("rule_id", "category", "classification", "description", "evidence", "automatic"):
                if not hasattr(rule, attribute):
                    raise ValueError(f"Rule is missing required metadata: {attribute}")
        self._packs[key] = pack

    def get(self, source: int, target: int) -> MigrationPack | None:
        return self._packs.get((source, target))

    def supports(self, source: int, target: int) -> bool:
        return (source, target) in self._packs

    def require(self, source: int, target: int) -> MigrationPack:
        pack = self.get(source, target)
        if not pack:
            raise UnsupportedMigrationPathError((UnsupportedMigrationStep(source, target),))
        return pack

    def missing_steps(self, steps) -> tuple[UnsupportedMigrationStep, ...]:
        return tuple(UnsupportedMigrationStep(step.source, step.target) for step in steps if not self.supports(step.source, step.target))

    def require_plan(self, steps) -> None:
        missing = self.missing_steps(steps)
        if missing:
            raise UnsupportedMigrationPathError(missing)

    def reachable_targets(self, source: int) -> tuple[int, ...]:
        targets = []
        current = source
        while self.supports(current, current + 1):
            current += 1
            targets.append(current)
        return tuple(targets)


def default_registry() -> MigrationPackRegistry:
    registry = MigrationPackRegistry()
    registry.register(MigrationPack(14, 15,
        analyzers=(
            lambda custom, source, target, diff: python.analyze(custom, source, target, diff),
            lambda custom, source, target, diff: xml.analyze(custom, source, target),
            lambda custom, source, target, diff: security.analyze(custom, target),
            lambda custom, source, target, diff: frontend.analyze(custom, source, target),
            lambda custom, source, target, diff: reports.analyze(custom, target),
        ),
        rule_factory=lambda: [Manifest14To15Rule()]))
    registry.register(MigrationPack(15, 16,
        analyzers=(
            lambda custom, source, target, diff: python16.analyze(custom, source, target, diff),
            lambda custom, source, target, diff: xml16.analyze(custom, source, target),
            lambda custom, source, target, diff: security16.analyze(custom, target),
            lambda custom, source, target, diff: frontend16.analyze(custom, source, target),
            lambda custom, source, target, diff: reports16.analyze(custom, target),
        ),
        rule_factory=lambda: [Manifest15To16Rule()]))
    registry.register(MigrationPack(16, 17,
        analyzers=(
            lambda custom, source, target, diff: python17.analyze(custom, source, target, diff),
            lambda custom, source, target, diff: dependencies17.analyze(custom, source, target, diff),
            lambda custom, source, target, diff: xml17.analyze(custom, source, target),
            lambda custom, source, target, diff: security17.analyze(custom, target),
            lambda custom, source, target, diff: frontend17.analyze(custom, source, target),
            lambda custom, source, target, diff: reports17.analyze(custom, target),
        ),
        rule_factory=lambda: [Manifest16To17Rule()]))
    registry.register(MigrationPack(17, 18,
        analyzers=(
            lambda custom, source, target, diff: python18.analyze(custom, source, target, diff),
            lambda custom, source, target, diff: dependencies18.analyze(custom, source, target, diff),
            lambda custom, source, target, diff: xml18.analyze(custom, source, target, diff),
            lambda custom, source, target, diff: security18.analyze(custom, target),
            lambda custom, source, target, diff: frontend18.analyze(custom, source, target),
            lambda custom, source, target, diff: reports18.analyze(custom, target),
        ),
        rule_factory=lambda: [Manifest17To18Rule(), xml18.TreeToListRule(), xml18.ActionViewModeTreeToListRule()]))
    registry.register(MigrationPack(18, 19,
        analyzers=(
            lambda custom, source, target, diff: python19.analyze(custom, source, target, diff),
            lambda custom, source, target, diff: dependencies19.analyze(custom, source, target, diff),
            lambda custom, source, target, diff: xml19.analyze(custom, source, target, diff),
            lambda custom, source, target, diff: security19.analyze(custom, target),
            lambda custom, source, target, diff: frontend19.analyze(custom, source, target),
            lambda custom, source, target, diff: reports19.analyze(custom, target),
        ),
        rule_factory=lambda: [Manifest18To19Rule()]))
    return registry
