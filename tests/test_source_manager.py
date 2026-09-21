from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.sources.manager import SourceManager, SourceManagerError
from odoo_migrator.sources.registry import SourceMode, SourceSpec, source_spec
from odoo_migrator.migrations.registry import default_registry


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    if not shutil.which("git"):
        pytest.skip("Git is required for source-manager integration tests")
    repo = tmp_path / "official"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Source Manager Tests")
    _git(repo, "checkout", "-b", "18.0")
    (repo / "snapshot.txt").write_text("verified\n", encoding="utf-8")
    _git(repo, "add", "snapshot.txt")
    _git(repo, "commit", "-m", "verified snapshot")
    verified = _git(repo, "rev-parse", "HEAD")
    (repo / "snapshot.txt").write_text("branch head\n", encoding="utf-8")
    _git(repo, "commit", "-am", "moving branch head")
    latest = _git(repo, "rev-parse", "HEAD")
    return repo, verified, latest


def _manager(tmp_path: Path, repo: Path, commit: str) -> SourceManager:
    spec = SourceSpec(18, "18.0", str(repo), commit)
    return SourceManager(tmp_path / "cache", source_specs={18: spec})


def test_verified_mode_detaches_to_pin_and_refresh_never_follows_branch(tmp_path: Path):
    repo, verified, latest = _repository(tmp_path)
    manager = _manager(tmp_path, repo, verified)

    snapshot = manager.ensure(18)
    assert snapshot.actual_commit == verified
    assert snapshot.expected_commit == verified
    assert snapshot.source_mode is SourceMode.VERIFIED_SNAPSHOT
    assert snapshot.path == manager.path_for(18)
    symbolic_ref = subprocess.run(
        ["git", "-C", str(snapshot.path), "symbolic-ref", "--short", "-q", "HEAD"],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    assert symbolic_ref.returncode != 0 and symbolic_ref.stdout.strip() == ""

    # The origin branch already points at a newer commit. Refresh is allowed
    # to refetch the exact object, but never to reset the verified cache to it.
    refreshed = manager.ensure(18, refresh=True)
    assert refreshed.actual_commit == verified
    assert refreshed.actual_commit != latest
    assert manager.snapshot(18).expected_commit == verified


def test_latest_mode_is_explicit_and_tracks_branch_on_refresh(tmp_path: Path):
    repo, verified, latest = _repository(tmp_path)
    manager = _manager(tmp_path, repo, verified)

    snapshot = manager.ensure(18, mode=SourceMode.LATEST_OFFICIAL_BRANCH)
    assert snapshot.source_mode is SourceMode.LATEST_OFFICIAL_BRANCH
    assert snapshot.expected_commit is None
    assert snapshot.actual_commit == latest
    assert manager.path_for(18, SourceMode.LATEST_OFFICIAL_BRANCH) != manager.path_for(18)

    (repo / "snapshot.txt").write_text("new branch head\n", encoding="utf-8")
    _git(repo, "commit", "-am", "new moving branch head")
    newest = _git(repo, "rev-parse", "HEAD")
    refreshed = manager.ensure(18, refresh=True, mode=SourceMode.LATEST_OFFICIAL_BRANCH)
    assert refreshed.actual_commit == newest
    assert refreshed.expected_commit is None


def test_unavailable_verified_commit_fails_clearly(tmp_path: Path):
    repo, _verified, _latest = _repository(tmp_path)
    unavailable = "0" * 40
    manager = _manager(tmp_path, repo, unavailable)
    with pytest.raises(SourceManagerError, match=unavailable):
        manager.ensure(18)


def test_wrong_origin_and_corrupt_cache_are_rejected(tmp_path: Path):
    repo, verified, _latest = _repository(tmp_path)
    wrong_root = tmp_path / "wrong"; wrong_root.mkdir()
    wrong, _wrong_verified, _wrong_latest = _repository(wrong_root)
    manager = _manager(tmp_path, repo, verified)

    destination = manager.path_for(18)
    destination.parent.mkdir(parents=True)
    _git(tmp_path / "wrong" / "official", "clone", str(wrong), str(destination))
    with pytest.raises(SourceManagerError, match="Unexpected source origin"):
        manager.ensure(18)

    corrupt_manager = _manager(tmp_path / "corrupt", repo, verified)
    corrupt = corrupt_manager.path_for(18)
    corrupt.mkdir(parents=True)
    (corrupt / "README.txt").write_text("not git", encoding="utf-8")
    with pytest.raises(SourceManagerError, match="not a Git repository"):
        corrupt_manager.ensure(18)


def test_source_snapshot_metadata_and_index_cache_identity_include_mode(tmp_path: Path):
    repo, verified, latest = _repository(tmp_path)
    manager = _manager(tmp_path, repo, verified)
    verified_snapshot = manager.ensure(18)
    latest_snapshot = manager.ensure(18, mode=SourceMode.LATEST_OFFICIAL_BRANCH)
    assert verified_snapshot.as_dict()["expected_commit"] == verified
    assert verified_snapshot.as_dict()["actual_commit"] == verified
    assert latest_snapshot.as_dict()["expected_commit"] is None
    assert latest_snapshot.as_dict()["actual_commit"] == latest

    cache = tmp_path / "indexes"
    indexer = SourceIndexer()
    indexer.index(repo, source_commit=verified, source_mode=verified_snapshot.source_mode.value,
                  source_version=18, cache_dir=cache)
    indexer.index(repo, source_commit=verified, source_mode=latest_snapshot.source_mode.value,
                  source_version=18, cache_dir=cache)
    assert len(list(cache.glob("*.json"))) == 2


def test_verified_snapshot_registry_contains_the_v1_chain():
    expected = {
        14: "cc0060e889603eb2e47fa44a8a22a70d7d784185",
        15: "3a28e5b0adbb36bdb1155a6854cdfbe4e7f9b187",
        16: "2df25c68396510abdb85f9b94ae0ba73f8cb340d",
        17: "5553002ba26972ba855585bfa37b54d4fee1fc56",
        18: "3c3e3b3d17cbd98584c7685e607d9085712adfe0",
        19: "dd153b3cb418c2e4d4302ac62398ef95d51c9891",
    }
    assert {version: source_spec(version).verified_commit for version in expected} == expected

    # Every adjacent pack's source/target evidence must resolve to the same
    # central registry values used by SourceManager.
    root = Path(__file__).parents[1] / "src" / "odoo_migrator" / "migrations"
    for source, target in ((14, 15), (15, 16), (16, 17), (17, 18), (18, 19)):
        evidence = (root / f"v{source}_to_v{target}" / "EVIDENCE.md").read_text(encoding="utf-8")
        assert source_spec(source).verified_commit in evidence
        assert source_spec(target).verified_commit in evidence

    manifest_rules = [
        rule
        for source, target in ((14, 15), (15, 16), (16, 17), (17, 18), (18, 19))
        for rule in default_registry().get(source, target).rule_factory()
        if rule.category == "manifest"
    ]
    for rule in manifest_rules:
        assert source_spec(rule.source).verified_commit in rule.evidence
        assert source_spec(rule.target).verified_commit in rule.evidence
