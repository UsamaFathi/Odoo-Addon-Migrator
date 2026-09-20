from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from odoo_migrator.core.versions import branch, normalize_version

OFFICIAL_COMMUNITY_REPO = "https://github.com/odoo/odoo.git"


@dataclass(frozen=True, slots=True)
class SourceSpec:
    version: int
    branch: str
    repo_url: str = OFFICIAL_COMMUNITY_REPO


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    version: int
    branch: str
    repo_url: str
    commit: str
    path: Path

    def as_dict(self) -> dict[str, str | int]:
        return {
            "version": self.version,
            "branch": self.branch,
            "repo_url": self.repo_url,
            "commit": self.commit,
            "path": str(self.path),
        }

    def save(self) -> None:
        payload = self.as_dict()
        (self.path / ".odoo_migrator_snapshot.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


def source_spec(version: int | str) -> SourceSpec:
    v = normalize_version(version)
    return SourceSpec(version=v, branch=branch(v))
