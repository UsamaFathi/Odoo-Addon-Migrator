from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from odoo_migrator.analysis.compat import Finding
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.base import MigrationRule
from odoo_migrator.migrations.v14_to_v15.manifest import Manifest14To15Rule
from odoo_migrator.migrations.v14_to_v15 import frontend, python, reports, security, xml


Analyzer = Callable[[OdooIndex, OdooIndex, OdooIndex, SourceDiff], list[Finding]]


@dataclass(frozen=True, slots=True)
class MigrationPack:
    source: int
    target: int
    analyzers: tuple[Analyzer, ...] = ()
    rule_factory: Callable[[], list[MigrationRule]] = lambda: []


class MigrationPackRegistry:
    def __init__(self):
        self._packs: dict[tuple[int, int], MigrationPack] = {}

    def register(self, pack: MigrationPack) -> None:
        self._packs[(pack.source, pack.target)] = pack

    def get(self, source: int, target: int) -> MigrationPack | None:
        return self._packs.get((source, target))


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
    return registry
