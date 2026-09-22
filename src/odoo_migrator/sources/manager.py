from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
import ast
import json
import shutil
import subprocess

from .registry import SourceMode, SourceSelection, SourceSnapshot, SourceSpec, source_spec


class SourceManagerError(RuntimeError):
    pass


class SourceManager:
    """Acquire reproducible official source trees without mixing source modes."""

    def __init__(self, cache_root: Path | None = None,
                 source_specs: Mapping[int, SourceSpec] | None = None):
        self.cache_root = Path(cache_root or Path.home() / ".odoo-addon-migrator" / "sources")
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._source_specs = dict(source_specs or {})

    def _spec(self, version: int | str) -> SourceSpec:
        canonical = source_spec(version)
        return self._source_specs.get(canonical.version, canonical)

    @staticmethod
    def _mode(mode: SourceMode | str) -> SourceMode:
        try:
            return mode if isinstance(mode, SourceMode) else SourceMode(mode)
        except ValueError as exc:
            raise SourceManagerError(f"Unsupported source mode: {mode!r}") from exc

    def path_for(self, version: int | str, mode: SourceMode | str = SourceMode.VERIFIED_SNAPSHOT) -> Path:
        spec = self._spec(version)
        selected = self._mode(mode)
        return self.cache_root / selected.value / spec.branch

    def ensure(self, version: int | str, refresh: bool = False,
               mode: SourceMode | str = SourceMode.VERIFIED_SNAPSHOT,
               local_path: Path | None = None) -> SourceSnapshot:
        spec = self._spec(version)
        selected = self._mode(mode)
        if selected is SourceMode.LOCAL_EXACT_SOURCE:
            if local_path is None:
                raise SourceManagerError(f"A local Odoo {spec.version} source path is required.")
            return self.resolve_local(spec.version, local_path)
        dest = self.path_for(spec.version, selected)
        git = shutil.which("git")
        if not git:
            raise SourceManagerError("Git is required to download/update Odoo Community source.")
        if selected is SourceMode.VERIFIED_SNAPSHOT and not spec.verified_commit:
            raise SourceManagerError(f"No verified commit is configured for Odoo {spec.version}.")

        if not (dest / ".git").exists():
            if dest.exists():
                raise SourceManagerError(f"Source path exists but is not a Git repository: {dest}")
            self._run([
                git, "clone", "--depth", "1", "--single-branch",
                "--branch", spec.branch, spec.repo_url, str(dest)
            ])

        origin = self._capture([git, "-C", str(dest), "remote", "get-url", "origin"])
        if not self._origin_matches(spec.repo_url, origin):
            raise SourceManagerError(
                f"Unexpected source origin for {dest}: {origin!r}; expected {spec.repo_url!r}"
            )
        self._reject_dirty_cache(dest, git)

        if selected is SourceMode.VERIFIED_SNAPSHOT:
            # Fetch only the configured object. Never fetch/reset the moving
            # branch for a verified cache, including when refresh=True.
            try:
                self._run([git, "-C", str(dest), "fetch", "--no-tags", "origin",
                           spec.verified_commit, "--depth", "1"])
            except SourceManagerError as first_error:
                # Some Git servers do not advertise arbitrary SHA wants.
                # Deepen from the official branch as a fallback, but still
                # checkout only the configured object and never reset to the
                # branch head.
                try:
                    self._run([git, "-C", str(dest), "fetch", "--no-tags", "origin", spec.branch])
                except SourceManagerError as fallback_error:
                    raise SourceManagerError(
                        f"Unable to fetch verified Odoo {spec.version} commit "
                        f"{spec.verified_commit}: {fallback_error}"
                    ) from first_error
            try:
                self._run([git, "-C", str(dest), "checkout", "--detach", "--force",
                           spec.verified_commit])
            except SourceManagerError as exc:
                raise SourceManagerError(
                    f"Verified Odoo {spec.version} commit is unavailable: {spec.verified_commit}"
                ) from exc
            expected = spec.verified_commit
        elif refresh:
            self._run([git, "-C", str(dest), "fetch", "--no-tags", "origin",
                       spec.branch, "--depth", "1"])
            self._run([git, "-C", str(dest), "reset", "--hard", f"origin/{spec.branch}"])
            expected = None
        else:
            expected = None

        commit = self._capture([git, "-C", str(dest), "rev-parse", "HEAD"])
        if selected is SourceMode.VERIFIED_SNAPSHOT and commit != spec.verified_commit:
            raise SourceManagerError(
                f"Verified Odoo {spec.version} checkout mismatch: expected "
                f"{spec.verified_commit}, got {commit}."
            )
        snapshot = SourceSnapshot(spec.version, spec.branch, origin, commit, dest, selected, expected)
        snapshot.save()
        return snapshot

    def resolve_selection(self, selection: SourceSelection, refresh: bool = False) -> SourceSnapshot:
        if selection.mode is SourceMode.LOCAL_EXACT_SOURCE:
            return self.resolve_local(selection.version, selection.path)
        return self.ensure(selection.version, refresh=refresh, mode=selection.mode)

    def resolve_local(self, version: int | str, path: Path) -> SourceSnapshot:
        """Validate and describe a user-owned Odoo tree without writing to it."""
        expected = self._spec(version).version
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise SourceManagerError(f"Local Odoo source directory does not exist: {root}")
        release = root / "odoo" / "release.py"
        if not release.is_file() or not (root / "addons").is_dir():
            raise SourceManagerError(f"Folder is not a recognizable Odoo source tree: {root}")
        detected = self._read_release_version(release)
        if detected != expected:
            raise SourceManagerError(f"Wrong Odoo source version. Expected: Odoo {expected}. Detected: Odoo {detected}.")
        git = shutil.which("git")
        is_git = (root / ".git").exists() and bool(git)
        is_git_repository = (root / ".git").exists()
        commit = branch_name = origin = None
        dirty = False
        if is_git:
            commit = self._try_capture([git, "-C", str(root), "rev-parse", "HEAD"])
            branch_name = self._try_capture([git, "-C", str(root), "symbolic-ref", "--short", "-q", "HEAD"])
            origin = self._try_capture([git, "-C", str(root), "remote", "get-url", "origin"])
            status = self._try_capture([git, "-C", str(root), "status", "--porcelain"])
            dirty = bool(status)
        return SourceSnapshot(
            expected, branch_name or f"{expected}.0", origin or "", commit, root,
            SourceMode.LOCAL_EXACT_SOURCE, None, origin, dirty, is_git_repository,
        )

    @staticmethod
    def _read_release_version(path: Path) -> int:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise SourceManagerError(f"Unable to read Odoo release metadata: {path}") from exc
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(target, ast.Name) and target.id == "version_info" for target in targets):
                continue
            value = node.value
            if isinstance(value, ast.Tuple) and value.elts and isinstance(value.elts[0], ast.Constant) and isinstance(value.elts[0].value, int):
                return int(value.elts[0].value)
        raise SourceManagerError(f"Odoo release version could not be identified from: {path}")

    def snapshot(self, version: int | str,
                 mode: SourceMode | str = SourceMode.VERIFIED_SNAPSHOT) -> SourceSnapshot | None:
        selected = self._mode(mode)
        dest = self.path_for(version, selected)
        meta = dest / ".odoo_migrator_snapshot.json"
        if not meta.exists():
            return None
        if not (dest / ".git").exists():
            return None
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            stored_mode = SourceMode(data.get("source_mode", selected.value))
            if stored_mode is not selected:
                raise SourceManagerError(f"Source cache metadata mode mismatch: {dest}")
            return SourceSnapshot(
                int(data["version"]), data["branch"], data["repo_url"],
                data.get("actual_commit") or data.get("commit"), dest, stored_mode,
                data.get("expected_commit"),
                data.get("origin"), bool(data.get("is_dirty", False)), bool(data.get("is_git_repository", True)),
                data.get("fingerprint"),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SourceManagerError(f"Invalid source snapshot metadata: {meta}") from exc

    @staticmethod
    def _normalize_origin(value: str) -> str:
        normalized = value.strip().removesuffix("/").removesuffix(".git")
        if normalized.startswith("git@github.com:"):
            normalized = "https://github.com/" + normalized.removeprefix("git@github.com:")
        return normalized

    @classmethod
    def _origin_matches(cls, expected: str, actual: str) -> bool:
        expected_path = Path(expected).resolve() if not "://" in expected and not expected.startswith("git@") else None
        actual_path = Path(actual).resolve() if not "://" in actual and not actual.startswith("git@") else None
        if expected_path is not None and actual_path is not None:
            return expected_path == actual_path
        return cls._normalize_origin(expected) == cls._normalize_origin(actual)

    @staticmethod
    def _reject_dirty_cache(dest: Path, git: str) -> None:
        status = SourceManager._capture([git, "-C", str(dest), "status", "--porcelain"])
        changes = [line for line in status.splitlines()
                   if line[3:].strip() != ".odoo_migrator_snapshot.json"]
        if changes:
            raise SourceManagerError(f"Source cache has local modifications and cannot be reused: {dest}")

    @staticmethod
    def _run(args: list[str]) -> None:
        try:
            subprocess.run(args, check=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stdout", None) or str(exc)
            raise SourceManagerError(f"Git command failed: {detail.strip()}") from exc

    @staticmethod
    def _capture(args: list[str]) -> str:
        try:
            return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "output", None) or str(exc)
            raise SourceManagerError(detail.strip()) from exc

    @staticmethod
    def _try_capture(args: list[str]) -> str | None:
        try:
            value = subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
            return value or None
        except (OSError, subprocess.CalledProcessError):
            return None
