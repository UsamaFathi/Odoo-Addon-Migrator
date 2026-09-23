from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import shutil
import subprocess
from time import perf_counter


_DEF_LINE = re.compile(r"^[+-]\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
DEFAULT_GIT_TIMEOUT_SECONDS = 120.0
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HistoryRename:
    source_method: str
    target_method: str
    file: str


@dataclass(frozen=True, slots=True)
class HistoryMiningResult:
    renames: tuple[HistoryRename, ...]
    status: str
    elapsed_seconds: float
    detail: str | None = None


def _resolve_ref(
    git: str,
    root: Path,
    version: int,
    *,
    timeout_seconds: float,
) -> str | None:
    branch = f"{version}.0"
    for ref in (
        f"refs/heads/{branch}",
        f"refs/remotes/origin/{branch}",
        f"refs/tags/{branch}",
    ):
        process = subprocess.run(
            [git, "-C", str(root), "rev-parse", "--verify", f"{ref}^{{commit}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        if process.returncode == 0 and process.stdout.strip():
            return ref
    return None


def mine_git_method_renames(
    repository: str | Path,
    source_version: int,
    target_version: int,
    *,
    timeout_seconds: float = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> tuple[HistoryRename, ...]:
    """Mine conservative method rename hints from adjacent branch diffs.

    Only a hunk with exactly one removed and one added Python function
    declaration is accepted. The source text itself is never returned or
    persisted in a Brain pack.
    """
    return mine_git_method_renames_with_status(
        repository,
        source_version,
        target_version,
        timeout_seconds=timeout_seconds,
    ).renames


def mine_git_method_renames_with_status(
    repository: str | Path,
    source_version: int,
    target_version: int,
    *,
    timeout_seconds: float = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> HistoryMiningResult:
    """Mine rename hints and expose non-fatal history diagnostics."""
    started = perf_counter()
    root = Path(repository).expanduser().resolve()
    git = shutil.which("git")
    if not git or not (root / ".git").exists():
        return HistoryMiningResult((), "unavailable", perf_counter() - started)

    try:
        old_ref = _resolve_ref(
            git, root, source_version, timeout_seconds=timeout_seconds
        )
        new_ref = _resolve_ref(
            git, root, target_version, timeout_seconds=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        elapsed = perf_counter() - started
        logger.warning(
            "Migration Brain Git history timed out step=%s_to_%s "
            "elapsed_seconds=%.3f timeout_seconds=%.1f",
            source_version,
            target_version,
            elapsed,
            timeout_seconds,
        )
        return HistoryMiningResult(
            (), "timeout", elapsed, f"Git history command exceeded {timeout_seconds:g}s"
        )
    if not old_ref or not new_ref:
        return HistoryMiningResult(
            (), "missing_refs", perf_counter() - started,
            "Adjacent version refs were not available in the repository.",
        )

    try:
        process = subprocess.run(
            [
                git, "-C", str(root), "diff", "--no-ext-diff", "--unified=3",
                old_ref, new_ref, "--", "*.py",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        elapsed = perf_counter() - started
        logger.warning(
            "Migration Brain Git history timed out step=%s_to_%s "
            "elapsed_seconds=%.3f timeout_seconds=%.1f",
            source_version,
            target_version,
            elapsed,
            timeout_seconds,
        )
        return HistoryMiningResult(
            (), "timeout", elapsed, f"Git history diff exceeded {timeout_seconds:g}s"
        )
    if process.returncode != 0:
        return HistoryMiningResult(
            (), "git_error", perf_counter() - started,
            f"git diff exited with status {process.returncode}",
        )

    current_file = ""
    removed: list[str] = []
    added: list[str] = []
    values: list[HistoryRename] = []

    def flush_hunk() -> None:
        nonlocal removed, added
        old_names = [name for name in removed if name not in added]
        new_names = [name for name in added if name not in removed]
        if len(old_names) == 1 and len(new_names) == 1 and old_names[0] != new_names[0]:
            values.append(HistoryRename(old_names[0], new_names[0], current_file))
        removed = []
        added = []

    for line in process.stdout.splitlines():
        if line.startswith("diff --git "):
            flush_hunk()
            parts = line.split()
            current_file = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else ""
            continue
        if line.startswith("@@"):
            flush_hunk()
            continue
        match = _DEF_LINE.match(line)
        if not match:
            continue
        if line.startswith("-"):
            removed.append(match.group(1))
        elif line.startswith("+"):
            added.append(match.group(1))
    flush_hunk()

    unique = {(item.source_method, item.target_method, item.file): item for item in values}
    renames = tuple(unique[key] for key in sorted(unique))
    elapsed = perf_counter() - started
    logger.info(
        "Migration Brain Git history step=%s_to_%s elapsed_seconds=%.3f rename_pairs=%d",
        source_version,
        target_version,
        elapsed,
        len(renames),
    )
    return HistoryMiningResult(renames, "complete", elapsed)
