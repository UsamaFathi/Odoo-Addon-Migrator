from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import tarfile
import tempfile


class EnterpriseSourceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EnterpriseSourceResolution:
    version: int
    selection_root: Path
    source_root: Path
    mode: str
    ref: str | None = None
    commit: str | None = None


def _has_manifests(root: Path) -> bool:
    try:
        return root.is_dir() and any(
            item.is_file() and item.name == "__manifest__.py"
            for item in root.rglob("__manifest__.py")
        )
    except OSError:
        return False


def validate_enterprise_tree(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise EnterpriseSourceError(f"Enterprise source folder does not exist: {root}")
    if not _has_manifests(root):
        raise EnterpriseSourceError(f"No Odoo addon manifests were found in Enterprise source: {root}")
    return root


def _capture(args: list[str]) -> str | None:
    try:
        value = subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
        return value or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_ref_for(root: Path, version: int) -> tuple[str, str] | None:
    git = shutil.which("git")
    if not git or not (root / ".git").exists():
        return None
    branch = f"{version}.0"
    for ref in (
        f"refs/heads/{branch}",
        f"refs/remotes/origin/{branch}",
        f"refs/tags/{branch}",
    ):
        commit = _capture([git, "-C", str(root), "rev-parse", "--verify", f"{ref}^{{commit}}"])
        if commit:
            return ref, commit
    return None


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive, "r") as handle:
        members = handle.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination):
                raise EnterpriseSourceError("Enterprise archive contains an unsafe path.")
            if member.issym() or member.islnk():
                raise EnterpriseSourceError("Enterprise archive contains symbolic links; refusing extraction.")
        handle.extractall(destination, members=members)


def _archive_git_ref(root: Path, version: int, ref: str, commit: str, cache_root: Path) -> Path:
    git = shutil.which("git")
    if not git:
        raise EnterpriseSourceError("Git is required to read Enterprise version branches.")
    destination = cache_root / f"{version}.0" / commit
    if _has_manifests(destination):
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".enterprise-{version}-", dir=destination.parent))
    archive = temporary / "source.tar"
    extracted = temporary / "tree"
    extracted.mkdir()
    try:
        process = subprocess.run(
            [git, "-C", str(root), "archive", "--format=tar", "--output", str(archive), ref],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise EnterpriseSourceError(
                f"Unable to read Enterprise Odoo {version} branch {ref}: {process.stdout.strip()}"
            )
        _safe_extract_tar(archive, extracted)
        validate_enterprise_tree(extracted)
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        os.replace(extracted, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return destination


def resolve_enterprise_source(
    selection_root: str | Path,
    version: int,
    *,
    cache_root: Path | None = None,
) -> EnterpriseSourceResolution:
    root = Path(selection_root).expanduser().resolve()
    if not root.is_dir():
        raise EnterpriseSourceError(f"Enterprise source directory does not exist: {root}")

    for name in (
        f"{version}.0",
        str(version),
        f"odoo-{version}",
        f"odoo{version}",
        f"enterprise-{version}",
    ):
        candidate = root / name
        if _has_manifests(candidate):
            return EnterpriseSourceResolution(version, root, candidate.resolve(), "version_folder")

    git_ref = _git_ref_for(root, version)
    if git_ref:
        ref, commit = git_ref
        cache = Path(cache_root or Path.home() / ".odoo-addon-migrator" / "enterprise-sources")
        tree = _archive_git_ref(root, version, ref, commit, cache)
        return EnterpriseSourceResolution(version, root, tree, "git_branch", ref, commit)

    if _has_manifests(root):
        # Odoo addon manifest "version" is module metadata, not a reliable
        # indicator of the Odoo major release. Enterprise addons commonly use
        # values such as "1.0", "2.0", or "4.0" on every supported Odoo
        # series. A direct user-selected addons tree is therefore accepted
        # based on its addon structure; versioned repo roots and Git branches
        # are resolved above when that stronger evidence exists.
        return EnterpriseSourceResolution(version, root, root, "direct_folder")

    raise EnterpriseSourceError(
        f"Could not resolve Odoo {version} Enterprise source from {root}. "
        f"Expected a {version}.0 folder or a local Git branch named {version}.0."
    )
