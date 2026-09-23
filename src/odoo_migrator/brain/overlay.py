from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from collections.abc import Callable, Mapping

from odoo_migrator.migrations.registry import MigrationPackRegistry, default_registry
from odoo_migrator.sources.enterprise import resolve_enterprise_source
from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.sources.manager import SourceManager

from .audit import assert_no_source_leakage, canonical_payload_bytes
from .pack import BrainPack
from .trainer import BrainTrainer, BrainTrainingResult


@dataclass(frozen=True, slots=True)
class EnterpriseOverlayResult:
    pack: BrainPack
    output: Path
    training: BrainTrainingResult


class EnterpriseOverlayTrainer:
    """Build local-only Enterprise knowledge bound to one Community Brain."""

    def __init__(
        self,
        *,
        source_manager: SourceManager | None = None,
        registry: MigrationPackRegistry | None = None,
        indexer: SourceIndexer | None = None,
    ):
        self.source_manager = source_manager or SourceManager()
        self.registry = registry or default_registry()
        self.indexer = indexer or SourceIndexer()

    def build(
        self,
        base_brain: BrainPack | str | Path,
        output: str | Path,
        *,
        enterprise_root: str | Path | None = None,
        enterprise_roots: Mapping[int, str | Path] | None = None,
        history_repo: str | Path | None = None,
        progress: Callable[[str, int], None] | None = None,
    ) -> EnterpriseOverlayResult:
        base = (
            base_brain
            if isinstance(base_brain, BrainPack)
            else BrainPack.load(base_brain)
        )
        if base.pack_kind != "community" or base.enterprise_knowledge:
            raise ValueError("Enterprise overlays require a Community-only base Brain.")
        if not base.fingerprint:
            raise ValueError("Enterprise overlays require a saved, fingerprinted base Brain.")
        if enterprise_root is None and not enterprise_roots:
            raise ValueError("Select authorized local Enterprise source for overlay training.")

        def report(message: str, percent: int) -> None:
            if progress:
                progress(message, max(0, min(100, int(percent))))

        resolved_roots: dict[int, Path] = {}
        for offset, version in enumerate(range(base.source, base.target + 1)):
            configured = (enterprise_roots or {}).get(version, enterprise_root)
            if configured is None:
                raise ValueError(
                    f"Enterprise source for Odoo {version} is required to avoid incomplete "
                    "adjacent-version knowledge."
                )
            report(
                f"Resolving authorized Enterprise Odoo {version} source",
                2 + round(offset / max(1, base.target - base.source) * 8),
            )
            resolved_roots[version] = resolve_enterprise_source(
                configured,
                version,
            ).source_root

        trainer = BrainTrainer(
            source_manager=self.source_manager,
            registry=self.registry,
            indexer=self.indexer,
        )
        with TemporaryDirectory(prefix="odoo-migrator-enterprise-overlay-") as temporary:
            composite_path = Path(temporary) / "enterprise-composite.omb"
            training = trainer.build(
                composite_path,
                source=base.source,
                target=base.target,
                enterprise_roots=resolved_roots,
                history_repo=history_repo,
                progress=lambda message, percent: report(
                    f"Enterprise overlay: {message}",
                    10 + round(percent * 0.80),
                ),
            )

        composite = training.pack
        self._validate_community_identity(base, composite)
        payload = deepcopy(composite.payload)
        payload.update({
            "schema_version": 4,
            "pack_kind": "enterprise_overlay",
            "base_fingerprint": base.fingerprint,
            "distribution_policy": "local_authorized_use_only",
            "enterprise_knowledge": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "fingerprint": "",
        })
        report("Auditing Enterprise overlay for source leakage", 92)
        audit = assert_no_source_leakage(payload, resolved_roots.values())
        payload["source_leakage_audit"] = audit.metadata()

        destination = BrainPack(payload).save(output)
        loaded = BrainPack.load(destination)
        report("Enterprise overlay ready", 100)
        return EnterpriseOverlayResult(loaded, destination, training)

    @staticmethod
    def _validate_community_identity(base: BrainPack, composite: BrainPack) -> None:
        if (base.source, base.target) != (composite.source, composite.target):
            raise ValueError("Enterprise overlay range does not match the base Community Brain.")
        for version in range(base.source, base.target + 1):
            key = str(version)
            expected = base.source_identities.get(key, {})
            actual = composite.source_identities.get(key, {})
            if expected.get("community_commit") != actual.get("community_commit"):
                raise ValueError(
                    f"Community Odoo {version} identity changed while building the Enterprise "
                    "overlay. Rebuild the Community Brain and overlay from the same snapshots."
                )


@dataclass(frozen=True, slots=True)
class BrainBundle:
    base: BrainPack
    overlay: BrainPack | None = None

    def __post_init__(self) -> None:
        if self.base.pack_kind != "community" or self.base.enterprise_knowledge:
            raise ValueError("BrainBundle base must be a Community-only Brain pack.")
        if self.overlay is None:
            return
        if self.overlay.pack_kind != "enterprise_overlay":
            raise ValueError("BrainBundle overlay must be an Enterprise overlay pack.")
        if self.overlay.base_fingerprint != self.base.fingerprint:
            raise ValueError("Enterprise overlay was built for a different Community Brain.")
        if (self.overlay.source, self.overlay.target) != (self.base.source, self.base.target):
            raise ValueError("Enterprise overlay range does not match the Community Brain.")

    @classmethod
    def load(
        cls,
        base: BrainPack | str | Path,
        overlay: BrainPack | str | Path | None = None,
    ) -> "BrainBundle":
        base_pack = base if isinstance(base, BrainPack) else BrainPack.load(base)
        overlay_pack = (
            overlay
            if isinstance(overlay, BrainPack) or overlay is None
            else BrainPack.load(overlay)
        )
        return cls(base_pack, overlay_pack)

    @property
    def active(self) -> BrainPack:
        return self.overlay or self.base

    @property
    def source(self) -> int:
        return self.base.source

    @property
    def target(self) -> int:
        return self.base.target

    @property
    def fingerprint(self) -> str:
        if self.overlay is None:
            return self.base.fingerprint
        return hashlib.sha256(
            f"{self.base.fingerprint}:{self.overlay.fingerprint}".encode("ascii")
        ).hexdigest()

    @property
    def training(self) -> dict:
        return self.active.training

    @property
    def source_identities(self) -> dict:
        return self.active.source_identities

    @property
    def enterprise_knowledge(self) -> bool:
        return self.overlay is not None

    @property
    def component_fingerprints(self) -> dict[str, str | None]:
        return {
            "community": self.base.fingerprint,
            "enterprise_overlay": self.overlay.fingerprint if self.overlay else None,
        }

    def supports(self, source: int, target: int) -> bool:
        return self.active.supports(source, target)

    def step(self, source: int, target: int) -> dict:
        return self.active.step(source, target)

    def canonical_identity(self) -> bytes:
        return canonical_payload_bytes(self.component_fingerprints)
