from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess

import pytest

from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.sources.composite import compose_indexes
from odoo_migrator.sources.enterprise import resolve_enterprise_source
from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.sources.registry import SourceSnapshot


class _Manager:
    def __init__(self, roots):
        self.roots = roots

    def snapshot(self, version, mode=None):
        return None

    def ensure(self, version):
        return SourceSnapshot(version, f"{version}.0", "controlled://community", None, self.roots[version])


def _addon(root: Path, name: str, version: int, *, depends=(), model: str | None = None) -> Path:
    module = root / name
    module.mkdir(parents=True, exist_ok=True)
    (module / "__manifest__.py").write_text(
        repr({"name": name, "version": f"{version}.0.1.0.0", "depends": list(depends)}),
        encoding="utf-8",
    )
    if model:
        (module / "models.py").write_text(
            "from odoo import fields, models\n"
            "class EnterpriseModel(models.Model):\n"
            f"    _name = {model!r}\n"
            "    name = fields.Char()\n",
            encoding="utf-8",
        )
    return module


def test_composite_index_includes_community_and_enterprise_modules(tmp_path: Path):
    community = tmp_path / "community"
    enterprise = tmp_path / "enterprise"
    _addon(community, "base", 18)
    _addon(enterprise, "account_reports", 18, model="account.report")
    indexer = SourceIndexer()

    merged = compose_indexes(
        indexer.index(community, cache_dir=tmp_path / "c-cache"),
        indexer.index(enterprise, cache_dir=tmp_path / "e-cache"),
    )

    assert "base" in merged.modules
    assert "account_reports" in merged.modules
    assert "account.report" in merged.models


def test_enterprise_source_prevents_false_dependency_and_model_blockers_and_replays_in_migration(tmp_path: Path):
    community18 = tmp_path / "community18"
    community19 = tmp_path / "community19"
    enterprise18 = tmp_path / "enterprise18"
    enterprise19 = tmp_path / "enterprise19"
    custom = tmp_path / "custom"

    _addon(community18, "base", 18)
    _addon(community19, "base", 19)
    _addon(enterprise18, "account_reports", 18, model="account.report")
    _addon(enterprise19, "account_reports", 19, model="account.report")
    module = _addon(custom, "custom_reports", 18, depends=("account_reports",))
    (module / "models.py").write_text(
        "from odoo import models\n"
        "class Report(models.Model):\n"
        "    _inherit = 'account.report'\n"
        "    def custom_value(self):\n"
        "        return True\n",
        encoding="utf-8",
    )

    analysis = AnalysisService().analyze(
        custom,
        18,
        19,
        manager=_Manager({18: community18, 19: community19}),
        enterprise_sources={18: enterprise18, 19: enterprise19},
    )

    assert not any(item.code in {"dependency.missing", "model.removed", "python.model.removed"} for item in analysis.findings)
    assert dict(analysis.enterprise_sources) == {18: str(enterprise18.resolve()), 19: str(enterprise19.resolve())}

    output = tmp_path / "output"
    result = MigrationService().migrate(custom, output, analysis)
    assert output.is_dir()
    assert (output / "custom_reports" / "__manifest__.py").is_file()
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["enterprise_sources"]["18"] == str(enterprise18.resolve())
    assert metadata["enterprise_sources"]["19"] == str(enterprise19.resolve())



def test_enterprise_version_folder_root_resolves_requested_version(tmp_path: Path):
    repo = tmp_path / "enterprise"
    _addon(repo / "16.0", "web_enterprise", 16)
    _addon(repo / "17.0", "web_enterprise", 17)

    sixteen = resolve_enterprise_source(repo, 16, cache_root=tmp_path / "cache")
    seventeen = resolve_enterprise_source(repo, 17, cache_root=tmp_path / "cache")

    assert sixteen.mode == "version_folder"
    assert sixteen.source_root == (repo / "16.0").resolve()
    assert seventeen.source_root == (repo / "17.0").resolve()


def test_enterprise_git_branches_are_archived_without_checkout(tmp_path: Path):
    git = shutil.which("git")
    if not git:
        pytest.skip("Git is unavailable")

    repo = tmp_path / "enterprise-repo"
    repo.mkdir()
    subprocess.run([git, "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run([git, "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run([git, "-C", str(repo), "config", "user.name", "Test"], check=True)

    _addon(repo, "web_enterprise", 16)
    subprocess.run([git, "-C", str(repo), "add", "."], check=True)
    subprocess.run([git, "-C", str(repo), "commit", "-m", "v16"], check=True, capture_output=True)
    subprocess.run([git, "-C", str(repo), "branch", "16.0"], check=True)

    shutil.rmtree(repo / "web_enterprise")
    _addon(repo, "web_enterprise", 17)
    subprocess.run([git, "-C", str(repo), "add", "-A"], check=True)
    subprocess.run([git, "-C", str(repo), "commit", "-m", "v17"], check=True, capture_output=True)
    subprocess.run([git, "-C", str(repo), "branch", "17.0"], check=True)

    head_before = subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    resolved = resolve_enterprise_source(repo, 16, cache_root=tmp_path / "cache")
    head_after = subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()

    assert resolved.mode == "git_branch"
    assert resolved.ref == "refs/heads/16.0"
    assert "16.0" in (
        resolved.source_root / "web_enterprise" / "__manifest__.py"
    ).read_text(encoding="utf-8")
    assert head_after == head_before



def test_direct_enterprise_folder_does_not_treat_module_versions_as_odoo_versions(tmp_path: Path):
    root = tmp_path / "enterprise16"
    for name, module_version in (
        ("web_enterprise", "1.0"),
        ("account_reports", "2.0"),
        ("documents", "4.0"),
    ):
        module = root / name
        module.mkdir(parents=True, exist_ok=True)
        (module / "__manifest__.py").write_text(
            repr({"name": name, "version": module_version, "depends": []}),
            encoding="utf-8",
        )

    resolved = resolve_enterprise_source(root, 16, cache_root=tmp_path / "cache")

    assert resolved.mode == "direct_folder"
    assert resolved.version == 16
    assert resolved.source_root == root.resolve()



def test_enterprise_root_discovers_common_enterprise_version_folder_names(tmp_path: Path):
    root = tmp_path / "enterprise-all"
    module = root / "odoo-enterprise-16.0" / "web_enterprise"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        repr({"name": "web_enterprise", "version": "1.0"}),
        encoding="utf-8",
    )

    resolved = resolve_enterprise_source(root, 16, cache_root=tmp_path / "cache")

    assert resolved.mode == "version_folder"
    assert resolved.source_root == (root / "odoo-enterprise-16.0").resolve()
