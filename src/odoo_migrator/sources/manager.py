from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess

from .registry import SourceSnapshot, source_spec


class SourceManagerError(RuntimeError):
    pass


class SourceManager:
    def __init__(self, cache_root: Path | None = None):
        self.cache_root = Path(cache_root or Path.home() / ".odoo-addon-migrator" / "sources")
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def path_for(self, version: int | str) -> Path:
        spec = source_spec(version)
        return self.cache_root / spec.branch

    def ensure(self, version: int | str, refresh: bool = False) -> SourceSnapshot:
        spec = source_spec(version)
        dest = self.path_for(spec.version)
        git = shutil.which("git")
        if not git:
            raise SourceManagerError("Git is required to download/update Odoo Community source.")

        if not (dest / ".git").exists():
            if dest.exists():
                raise SourceManagerError(f"Source path exists but is not a Git repository: {dest}")
            self._run([
                git, "clone", "--depth", "1", "--single-branch",
                "--branch", spec.branch, spec.repo_url, str(dest)
            ])
        elif refresh:
            self._run([git, "-C", str(dest), "fetch", "origin", spec.branch, "--depth", "1"])
            self._run([git, "-C", str(dest), "reset", "--hard", f"origin/{spec.branch}"])

        origin = self._capture([git, "-C", str(dest), "remote", "get-url", "origin"])
        if "github.com/odoo/odoo" not in origin.replace(".git", ""):
            raise SourceManagerError(f"Unexpected source origin for {dest}: {origin}")
        commit = self._capture([git, "-C", str(dest), "rev-parse", "HEAD"])
        snapshot = SourceSnapshot(spec.version, spec.branch, origin, commit, dest)
        snapshot.save()
        return snapshot

    def snapshot(self, version: int | str) -> SourceSnapshot | None:
        dest = self.path_for(version)
        meta = dest / ".odoo_migrator_snapshot.json"
        if not meta.exists():
            return None
        data = json.loads(meta.read_text(encoding="utf-8"))
        return SourceSnapshot(
            int(data["version"]), data["branch"], data["repo_url"], data["commit"], dest
        )

    @staticmethod
    def _run(args: list[str]) -> None:
        try:
            subprocess.run(args, check=True)
        except subprocess.CalledProcessError as exc:
            raise SourceManagerError(f"Command failed with exit code {exc.returncode}: {args[0]}") from exc

    @staticmethod
    def _capture(args: list[str]) -> str:
        try:
            return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
        except subprocess.CalledProcessError as exc:
            raise SourceManagerError(exc.output.strip()) from exc
