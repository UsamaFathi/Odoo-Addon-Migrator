from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import json

from odoo_migrator.core.versions import branch, normalize_version

OFFICIAL_COMMUNITY_REPO = "https://github.com/odoo/odoo.git"

VERIFIED_COMMUNITY_COMMITS: dict[int, str] = {
    14: "cc0060e889603eb2e47fa44a8a22a70d7d784185",
    15: "3a28e5b0adbb36bdb1155a6854cdfbe4e7f9b187",
    16: "2df25c68396510abdb85f9b94ae0ba73f8cb340d",
    17: "5553002ba26972ba855585bfa37b54d4fee1fc56",
    18: "3c3e3b3d17cbd98584c7685e607d9085712adfe0",
    19: "dd153b3cb418c2e4d4302ac62398ef95d51c9891",
}


class SourceMode(str, Enum):
    VERIFIED_SNAPSHOT = "verified_snapshot"
    LATEST_OFFICIAL_BRANCH = "latest_official_branch"


@dataclass(frozen=True, slots=True)
class SourceSpec:
    version: int
    branch: str
    repo_url: str = OFFICIAL_COMMUNITY_REPO
    verified_commit: str | None = None


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    version: int
    branch: str
    repo_url: str
    commit: str
    path: Path
    source_mode: SourceMode = SourceMode.VERIFIED_SNAPSHOT
    expected_commit: str | None = None

    @property
    def actual_commit(self) -> str:
        """The commit actually checked out in this source tree."""
        return self.commit

    def as_dict(self) -> dict[str, str | int | None]:
        mode = self.source_mode.value if isinstance(self.source_mode, SourceMode) else str(self.source_mode)
        return {
            "version": self.version,
            "branch": self.branch,
            "repo_url": self.repo_url,
            # Keep the old key for metadata/API compatibility while exposing
            # unambiguous names for reproducibility.
            "commit": self.commit,
            "source_mode": mode,
            "expected_commit": self.expected_commit,
            "actual_commit": self.actual_commit,
            "path": str(self.path),
        }

    def save(self) -> None:
        payload = self.as_dict()
        (self.path / ".odoo_migrator_snapshot.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


def source_spec(version: int | str) -> SourceSpec:
    v = normalize_version(version)
    return SourceSpec(version=v, branch=branch(v), verified_commit=VERIFIED_COMMUNITY_COMMITS[v])
