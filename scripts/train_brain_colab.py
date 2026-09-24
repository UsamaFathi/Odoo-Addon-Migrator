from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter

from odoo_migrator.brain.overlay import EnterpriseOverlayTrainer
from odoo_migrator.brain.pack import BrainPack
from odoo_migrator.brain.runtime import BrainRuntimeMigrator
from odoo_migrator.brain.trainer import BrainTrainer
from odoo_migrator.sources.enterprise import resolve_enterprise_source
from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.sources.manager import SourceManager
from odoo_migrator.sources.registry import VERIFIED_COMMUNITY_COMMITS


LOGGER = logging.getLogger("odoo_migrator.colab_training")


class CachedSourceIndexer(SourceIndexer):
    """Use an explicit cache instead of Colab's disposable home directory."""

    def __init__(self, cache_dir: Path):
        super().__init__()
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def index(self, root: Path, **kwargs):  # type: ignore[override]
        kwargs.setdefault("cache_dir", self.cache_dir)
        return super().index(root, **kwargs)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Community and authorized Enterprise Migration Brain packs."
    )
    parser.add_argument("--enterprise-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, default=Path("/content/oam-training"))
    parser.add_argument("--from-version", type=int, default=14)
    parser.add_argument("--to-version", type=int, default=19)
    parser.add_argument(
        "--stage-enterprise",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Copy authorized Enterprise trees to Colab local storage before indexing.",
    )
    parser.add_argument(
        "--reuse-community",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--reuse-overlay",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--skip-smoke", action="store_true")
    return parser.parse_args()


def _configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )


def _progress(prefix: str, started: float):
    def report(message: str, percent: int) -> None:
        elapsed = perf_counter() - started
        LOGGER.info("%s %3d%% | %s | elapsed %.1fs", prefix, percent, message, elapsed)

    return report


def _copy_tree_read_only(source: Path, destination: Path) -> None:
    """Copy to disposable work storage without writing to the selected source."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".copying")
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(
        source,
        temporary,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo"),
    )
    if destination.exists():
        shutil.rmtree(destination)
    temporary.replace(destination)


def _resolve_enterprise_roots(
    root: Path,
    source: int,
    target: int,
    work_dir: Path,
    *,
    stage: bool,
) -> dict[int, Path]:
    resolved: dict[int, Path] = {}
    for version in range(source, target + 1):
        resolution = resolve_enterprise_source(root, version)
        selected = resolution.source_root
        LOGGER.info(
            "Validated authorized Enterprise Odoo %d source mode=%s",
            version,
            resolution.mode,
        )
        if stage:
            staged = work_dir / "enterprise" / f"{version}.0"
            LOGGER.info("Staging Enterprise Odoo %d to Colab local storage", version)
            copy_started = perf_counter()
            _copy_tree_read_only(selected, staged)
            LOGGER.info(
                "Staged Enterprise Odoo %d elapsed_seconds=%.3f",
                version,
                perf_counter() - copy_started,
            )
            selected = staged
        resolved[version] = selected
    return resolved


def _load_reusable_community(path: Path, source: int, target: int) -> BrainPack | None:
    if not path.is_file():
        return None
    pack = BrainPack.load(path)
    if pack.pack_kind != "community" or (pack.source, pack.target) != (source, target):
        raise ValueError(f"Existing Community Brain is incompatible: {path}")
    for version in range(source, target + 1):
        actual = pack.source_identities.get(str(version), {}).get("community_commit")
        expected = VERIFIED_COMMUNITY_COMMITS[version]
        if actual != expected:
            raise ValueError(
                f"Existing Community Brain uses the wrong Odoo {version} commit: "
                f"expected {expected}, got {actual}."
            )
    return pack


def _load_reusable_overlay(
    path: Path,
    base: BrainPack,
    source: int,
    target: int,
) -> BrainPack | None:
    if not path.is_file():
        return None
    pack = BrainPack.load(path)
    if pack.pack_kind != "enterprise_overlay" or (pack.source, pack.target) != (source, target):
        raise ValueError(f"Existing Enterprise overlay is incompatible: {path}")
    if pack.base_fingerprint != base.fingerprint:
        raise ValueError("Existing Enterprise overlay belongs to a different Community Brain.")
    return pack


def _publish(local_path: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(local_path, temporary)
    temporary.replace(destination)
    return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _project_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _source_free_smoke(
    work_dir: Path,
    community: Path,
    overlay: Path,
) -> dict[str, object]:
    smoke_root = work_dir / "source-free-smoke"
    if smoke_root.exists():
        shutil.rmtree(smoke_root)
    custom = smoke_root / "custom_addons"
    addon = custom / "brain_smoke_addon"
    addon.mkdir(parents=True)
    (addon / "__init__.py").write_text("", encoding="utf-8")
    manifest = addon / "__manifest__.py"
    manifest.write_text(
        "{'name': 'Brain smoke addon', 'version': '16.0.1.0.0', "
        "'depends': ['base'], 'installable': True}\n",
        encoding="utf-8",
    )
    before = SourceIndexer.project_fingerprint(custom)
    output = smoke_root / "migrated"
    result = BrainRuntimeMigrator(community, overlay=overlay).migrate(
        custom,
        output,
        source=16,
        target=18,
    )
    after = SourceIndexer.project_fingerprint(custom)
    if before != after:
        raise AssertionError("Source-free smoke migration modified its input project.")
    migrated_manifest = (output / addon.name / "__manifest__.py").read_text(encoding="utf-8")
    if "18.0.1.0.0" not in migrated_manifest:
        raise AssertionError("Source-free smoke migration did not reach Odoo 18.")
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    if metadata.get("source_code_indexed_at_runtime") is not False:
        raise AssertionError("Brain runtime unexpectedly depended on Odoo source.")
    return {
        "path": "16_to_17,17_to_18",
        "validation_state": result.validation_state,
        "input_unchanged": True,
        "source_code_indexed_at_runtime": False,
    }


def main() -> int:
    args = _parse_args()
    source = args.from_version
    target = args.to_version
    if source < 14 or target > 19 or target <= source:
        raise ValueError("This notebook supports the verified Odoo 14 through 19 range.")

    work_dir = args.work_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "migration_brain_training.log"
    _configure_logging(log_path)
    started = perf_counter()

    LOGGER.info("Migration Brain training started range=%d->%d", source, target)
    LOGGER.info("Project commit=%s", _project_commit() or "unavailable")
    roots = _resolve_enterprise_roots(
        args.enterprise_root.expanduser().resolve(),
        source,
        target,
        work_dir,
        stage=args.stage_enterprise,
    )

    manager = SourceManager(cache_root=work_dir / "cache" / "sources")
    indexer = CachedSourceIndexer(work_dir / "cache" / "indexes")
    community_destination = output_dir / f"migration_brain_community_{source}_{target}.omb"
    community = (
        _load_reusable_community(community_destination, source, target)
        if args.reuse_community
        else None
    )
    if community is None:
        local_community = work_dir / community_destination.name
        result = BrainTrainer(source_manager=manager, indexer=indexer).build(
            local_community,
            source=source,
            target=target,
            progress=_progress("COMMUNITY", started),
        )
        _publish(result.output, community_destination)
        community = BrainPack.load(community_destination)
    else:
        LOGGER.info("Reusing verified Community Brain fingerprint=%s", community.fingerprint)

    overlay_destination = output_dir / f"enterprise_overlay_{source}_{target}.omb"
    overlay = (
        _load_reusable_overlay(overlay_destination, community, source, target)
        if args.reuse_overlay
        else None
    )
    if overlay is None:
        local_overlay = work_dir / overlay_destination.name
        result = EnterpriseOverlayTrainer(
            source_manager=manager,
            indexer=indexer,
        ).build(
            community,
            local_overlay,
            enterprise_roots=roots,
            progress=_progress("ENTERPRISE", started),
        )
        _publish(result.output, overlay_destination)
        overlay = BrainPack.load(overlay_destination)
    else:
        LOGGER.info("Reusing Enterprise overlay fingerprint=%s", overlay.fingerprint)

    smoke = None
    if not args.skip_smoke:
        LOGGER.info("Running source-free 16 -> 18 smoke migration")
        smoke = _source_free_smoke(
            work_dir,
            community_destination,
            overlay_destination,
        )

    artifacts = {
        community_destination.name: _sha256(community_destination),
        overlay_destination.name: _sha256(overlay_destination),
    }
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_commit": _project_commit(),
        "source_version": source,
        "target_version": target,
        "verified_community_commits": {
            str(version): VERIFIED_COMMUNITY_COMMITS[version]
            for version in range(source, target + 1)
        },
        "community": {
            "file": community_destination.name,
            "fingerprint": community.fingerprint,
            "pack_kind": community.pack_kind,
            "distribution_policy": community.distribution_policy,
            "production_validation": community.training.get("production_validation", {}),
        },
        "enterprise_overlay": {
            "file": overlay_destination.name,
            "fingerprint": overlay.fingerprint,
            "base_fingerprint": overlay.base_fingerprint,
            "pack_kind": overlay.pack_kind,
            "distribution_policy": overlay.distribution_policy,
            "source_leakage_audit": overlay.payload.get("source_leakage_audit", {}),
            "production_validation": overlay.training.get("production_validation", {}),
        },
        "source_free_smoke": smoke,
        "sha256": artifacts,
        "elapsed_seconds": round(perf_counter() - started, 3),
    }
    summary_path = output_dir / "migration_brain_training_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    checksum_path = output_dir / "SHA256SUMS.txt"
    checksum_path.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in artifacts.items()),
        encoding="utf-8",
    )
    LOGGER.info("Community Brain: %s", community_destination)
    LOGGER.info("Enterprise overlay: %s", overlay_destination)
    LOGGER.info("Training summary: %s", summary_path)
    LOGGER.info("Completed elapsed_seconds=%.3f", perf_counter() - started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
