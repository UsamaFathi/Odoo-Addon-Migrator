from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from collections.abc import Iterable, Mapping
from typing import Any


_SOURCE_SUFFIXES = frozenset({
    ".py", ".xml", ".js", ".mjs", ".scss", ".css", ".csv", ".json",
    ".po", ".pot", ".html", ".txt",
})
_IGNORED_PARTS = frozenset({".git", "__pycache__", ".pytest_cache", "node_modules"})


@dataclass(frozen=True, slots=True)
class SourceLeakageAudit:
    files_scanned: int
    fragments_checked: int
    matches: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.matches

    def metadata(self) -> dict[str, int | str]:
        return {
            "status": "passed" if self.passed else "failed",
            "files_scanned": self.files_scanned,
            "fragments_checked": self.fragments_checked,
        }


def _normalize_fragment(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _payload_strings(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _payload_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _payload_strings(item)
    elif isinstance(value, str):
        yield value


def audit_payload_against_sources(
    payload: Mapping[str, Any],
    source_roots: Iterable[str | Path],
    *,
    minimum_fragment_length: int = 64,
) -> SourceLeakageAudit:
    """Detect verbatim source lines accidentally embedded in derived knowledge.

    The audit stores only hashes of matching fragments. It deliberately avoids
    returning or logging Enterprise source text.
    """
    payload_fragments = {
        normalized
        for value in _payload_strings(payload)
        for line in value.splitlines()
        if len(normalized := _normalize_fragment(line)) >= minimum_fragment_length
    }
    if not payload_fragments:
        return SourceLeakageAudit(0, 0)

    files_scanned = 0
    fragments_checked = 0
    matches: set[str] = set()
    for configured_root in source_roots:
        root = Path(configured_root).expanduser().resolve()
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
                continue
            try:
                relative = path.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            if any(part in _IGNORED_PARTS for part in relative.parts):
                continue
            try:
                if path.stat().st_size > 4 * 1024 * 1024:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files_scanned += 1
            for line in text.splitlines():
                normalized = _normalize_fragment(line)
                if len(normalized) < minimum_fragment_length:
                    continue
                fragments_checked += 1
                if normalized in payload_fragments:
                    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                    matches.add(f"{relative.as_posix()}:{digest[:16]}")

    return SourceLeakageAudit(
        files_scanned,
        fragments_checked,
        tuple(sorted(matches)),
    )


def assert_no_source_leakage(
    payload: Mapping[str, Any],
    source_roots: Iterable[str | Path],
) -> SourceLeakageAudit:
    audit = audit_payload_against_sources(payload, source_roots)
    if not audit.passed:
        raise ValueError(
            "Migration Brain source leakage audit failed; derived pack data matched "
            f"{len(audit.matches)} Enterprise source fragment(s). "
            "The pack was not written. Match fingerprints: "
            + ", ".join(audit.matches[:5])
        )
    return audit


def canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    """Stable serialization helper used by overlay integrity checks."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
