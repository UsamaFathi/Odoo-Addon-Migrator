from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "train_migration_brain_colab.ipynb"
SCRIPT = ROOT / "scripts" / "train_brain_colab.py"
PACKAGE_SCRIPT = ROOT / "scripts" / "package_enterprise_for_colab.py"


def _load_script(path: Path = SCRIPT):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _enterprise_tree(root: Path, version: int) -> Path:
    addon = root / f"{version}.0" / "sale_enterprise"
    addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text(
        repr({"name": "Enterprise fixture", "version": f"{version}.0.1.0.0"}),
        encoding="utf-8",
    )
    (addon / "models.py").write_text("VALUE = 'private fixture marker'\n", encoding="utf-8")
    return addon.parent


def test_colab_notebook_is_valid_and_uses_reproducible_training_driver():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    sources = "\n".join(
        "".join(cell.get("source", ()))
        for cell in notebook["cells"]
    )

    assert "drive.mount('/content/drive')" in sources
    assert "1yKOhhT2-Quhy_Va42a4-rUkdsoB7FtYt" in sources
    assert "e32b5c7e746a97b7a038617e40ca6ffae25878ed" in sources
    assert "userdata.get('GITHUB_TOKEN')" in sources
    assert "GIT_CONFIG_VALUE_0" in sources
    assert "x-access-token:{github_token}" in sources
    assert "BrainTrainer" in sources
    assert "EnterpriseOverlayTrainer" in sources
    assert "STAGE_ENTERPRISE_LOCALLY" in sources
    assert "USE_ENTERPRISE_ARCHIVES = True" in sources
    assert "odoo-enterprise-{version}.0.zip" in sources
    assert "Transfer {source.name}" in sources
    assert "Unsafe archive member" in sources
    assert "source_code_indexed_at_runtime" in sources
    assert "local_authorized_use_only" in sources

    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), f"notebook-cell-{index}", "exec")


def test_colab_enterprise_staging_is_read_only_and_version_specific(tmp_path: Path):
    module = _load_script()
    enterprise = tmp_path / "drive-enterprise"
    originals: dict[int, bytes] = {}
    for version in range(14, 20):
        tree = _enterprise_tree(enterprise, version)
        originals[version] = (tree / "sale_enterprise" / "models.py").read_bytes()

    resolved = module._resolve_enterprise_roots(
        enterprise,
        14,
        19,
        tmp_path / "work",
        stage=True,
    )

    assert set(resolved) == set(range(14, 20))
    assert len(set(resolved.values())) == 6
    for version, staged in resolved.items():
        assert staged == (tmp_path / "work" / "enterprise" / f"{version}.0").resolve()
        assert (staged / "sale_enterprise" / "__manifest__.py").is_file()
        original = enterprise / f"{version}.0" / "sale_enterprise" / "models.py"
        assert original.read_bytes() == originals[version]


def test_colab_notebook_does_not_embed_credentials_or_enterprise_source():
    text = NOTEBOOK.read_text(encoding="utf-8")
    lowered = text.casefold()
    assert "client_secret" not in lowered
    assert "access_token" not in lowered
    assert "private_key" not in lowered
    assert "source_text" not in lowered
    assert "target_text" not in lowered


def test_enterprise_archive_packaging_is_read_only_and_colab_friendly(tmp_path: Path):
    module = _load_script(PACKAGE_SCRIPT)
    enterprise = tmp_path / "enterprise"
    source = _enterprise_tree(enterprise, 18)
    cache = source / "sale_enterprise" / "__pycache__"
    cache.mkdir()
    (cache / "models.pyc").write_bytes(b"compiled")
    marker = source / "sale_enterprise" / "models.py"
    before = marker.read_bytes()

    archive = module.package_version(enterprise, tmp_path / "archives", 18)

    assert archive.name == "odoo-enterprise-18.0.zip"
    assert marker.read_bytes() == before
    with zipfile.ZipFile(archive) as bundle:
        members = set(bundle.namelist())
    assert "18.0/sale_enterprise/__manifest__.py" in members
    assert "18.0/sale_enterprise/models.py" in members
    assert not any("__pycache__" in member or member.endswith(".pyc") for member in members)
